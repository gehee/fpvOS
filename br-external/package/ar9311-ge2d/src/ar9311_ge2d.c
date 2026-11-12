// SPDX-License-Identifier: GPL-2.0-or-later
/* AR9311 memory-to-memory video/HUD compositor. Register/command behavior
 * established by offscreen hardware tests; no vendor runtime dependency.
 */
#include <linux/capability.h>
#include <linux/compat.h>
#include <linux/completion.h>
#include <linux/delay.h>
#include <linux/dma-buf.h>
#include <linux/dma-mapping.h>
#include <linux/dma-resv.h>
#include <linux/interrupt.h>
#include <linux/io.h>
#include <linux/miscdevice.h>
#include <linux/mfd/syscon.h>
#include <linux/regmap.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include "ar9311_ge2d.h"

#define GE_WIDTH 1920
#define GE_HEIGHT 1080
#define GE_COMMAND_BYTES 4096
#define GE_MAPS (6 + AR_GE2D_MAX_OVERLAYS)
#define GE_CSC_709_LIMITED 2

struct ge_map {
	struct dma_buf *buf;
	struct dma_buf_attachment *attachment;
	struct sg_table *sgt;
	dma_addr_t address;
	u64 start, end;
	u64 size; /* contiguous bytes at address */
};
struct ge_job {
	struct ge_map maps[GE_MAPS];
	u32 used;
};
struct ge_device {
	struct device *dev;
	void __iomem *regs;
	struct regmap *crg;
	struct miscdevice misc;
	struct mutex lock;
	struct completion done;
	atomic_t opened;
	u32 *commands;
	dma_addr_t commands_dma;
	u32 status, completed, sequence;
	bool initialized, poisoned;
	bool stale; /* set up again before the next job */
	struct ge_job *retained;
};

static irqreturn_t ge_irq(int irq, void *opaque)
{
	struct ge_device *ge = opaque;
	u32 status;

	if (!READ_ONCE(ge->initialized))
		return IRQ_NONE;
	status = readl(ge->regs + 0x0c);
	if (!(status & 0x1fc2))
		return IRQ_NONE;
	writel(status, ge->regs + 0x0c);
	ge->status = status;
	/* Reading an empty completion FIFO underflows it. Only pop on DONE. */
	ge->completed = status & 2 ? readl(ge->regs + 0x60) : 0x100;
	complete(&ge->done);
	return IRQ_HANDLED;
}

static int ge_initialize(struct ge_device *ge)
{
	u32 value;

	if (ge->initialized && !ge->stale)
		return 0;
	if (regmap_read(ge->crg, 0, &value))
		return -EIO;
	/* The display initializes the shared DC domain. Never reset it here. */
	if ((value & 0x600) != 0x600)
		return -EHOSTDOWN;
	regmap_update_bits(ge->crg, 0, BIT(16) | BIT(17) | BIT(18) | BIT(28),
			   BIT(17) | BIT(28));
	regmap_update_bits(ge->crg, 0, BIT(25) | BIT(26), 0);
	usleep_range(2000, 3000);
	regmap_update_bits(ge->crg, 0, BIT(25) | BIT(26), BIT(25) | BIT(26));
	usleep_range(2000, 3000);
	writel(0x20000000, ge->regs + 0x78);
	writel(readl(ge->regs) | 0x7f, ge->regs);
	usleep_range(2000, 3000);
	writel(readl(ge->regs) & ~0x7f, ge->regs);
	writel(0, ge->regs + 0x2c);
	writel((readl(ge->regs + 0x30) | 1) & ~0xe, ge->regs + 0x30);
	writel(0xffff0000, ge->regs + 0x64);
	writel(0xffff0000, ge->regs + 0x68);
	writel(0xffff0000, ge->regs + 0x6c);
	writel(0xffff0000, ge->regs + 0x70);
	writel(0, ge->regs + 0x74);
	writel(0, ge->regs + 0xb8);
	writel(readl(ge->regs + 0x10) | 1, ge->regs + 0x10);
	writel(readl(ge->regs + 0x18) | 9, ge->regs + 0x18);
	writel(0xffff, ge->regs + 0x0c);
	ge->stale = false;
	WRITE_ONCE(ge->initialized, true);
	writel(readl(ge->regs + 8) & 0xffff0000, ge->regs + 8);
	return 0;
}

static void ge_unmap(struct ge_job *job)
{
	while (job->used) {
		struct ge_map *m = &job->maps[--job->used];

		if (m->sgt)
			dma_buf_unmap_attachment_unlocked(m->attachment, m->sgt,
							 DMA_BIDIRECTIONAL);
		if (m->attachment)
			dma_buf_detach(m->buf, m->attachment);
		if (m->buf)
			dma_buf_put(m->buf);
	}
}

static int ge_import(struct ge_device *ge, struct ge_job *job, unsigned int first,
		     int fd, u32 offset, u64 bytes, bool output, u32 *address)
{
	struct ge_map *m = &job->maps[job->used++];
	struct scatterlist *sg;
	dma_addr_t next;
	u64 total = 0;
	long waited;
	unsigned int i;
	int ret;

	m->buf = dma_buf_get(fd);
	if (IS_ERR(m->buf)) {
		ret = PTR_ERR(m->buf);
		m->buf = NULL;
		return ret;
	}
	if ((offset & 31) || offset > m->buf->size ||
	    bytes > m->buf->size - offset)
		return -EINVAL;
	m->start = offset;
	m->end = offset + bytes;
	/* Planes of one image usually share a buffer: wait, attach and map it
	 * once, so cache maintenance runs once per buffer, not per plane.
	 */
	for (i = first; i + 1 < job->used; i++) {
		const struct ge_map *o = &job->maps[i];

		if (o->buf == m->buf && o->sgt) {
			m->address = o->address;
			m->size = o->size;
			goto check;
		}
	}
	waited = dma_resv_wait_timeout(m->buf->resv,
		output ? DMA_RESV_USAGE_READ : DMA_RESV_USAGE_WRITE,
		true, msecs_to_jiffies(500));
	if (waited <= 0)
		return waited ?: -EBUSY;
	m->attachment = dma_buf_attach(m->buf, ge->dev);
	if (IS_ERR(m->attachment)) {
		ret = PTR_ERR(m->attachment);
		m->attachment = NULL;
		return ret;
	}
	m->sgt = dma_buf_map_attachment_unlocked(m->attachment,
					       DMA_BIDIRECTIONAL);
	if (IS_ERR(m->sgt)) {
		ret = PTR_ERR(m->sgt);
		m->sgt = NULL;
		return ret;
	}
	if (!m->sgt->nents)
		return -EINVAL;
	m->address = sg_dma_address(m->sgt->sgl);
	next = m->address;
	for_each_sgtable_dma_sg(m->sgt, sg, i) {
		if (sg_dma_address(sg) != next)
			return -EINVAL;
		total += sg_dma_len(sg);
		next += sg_dma_len(sg);
	}
	m->size = total;
check:
	if (m->end > m->size || (u64)m->address + m->end > (1ULL << 32))
		return -ERANGE;
	*address = m->address + offset;
	return 0;
}

static bool ge_overlaps(const struct ge_map *a, const struct ge_map *b)
{
	return (u64)a->address + a->start < (u64)b->address + b->end &&
	       (u64)b->address + b->start < (u64)a->address + a->end;
}

static int ge_image(struct ge_device *ge, struct ge_job *job,
		    const struct ar_ge2d_image *image, bool output, u32 *addresses)
{
	unsigned int planes = image->format == AR_GE2D_YUV420 ? 3 : 1;
	unsigned int i, first = job->used;
	int ret;

	if (!image->width || !image->height || image->width > GE_WIDTH ||
	    image->height > GE_HEIGHT ||
	    (image->format != AR_GE2D_YUV420 && image->format != AR_GE2D_ARGB8888))
		return -EINVAL;
	if (planes == 3 && ((image->width | image->height) & 1))
		return -EINVAL;
	for (i = 0; i < planes; i++) {
		u32 row = planes == 1 ? image->width * 4 : image->width >> !!i;
		u32 rows = image->height >> !!i;
		u32 unit = planes == 1 ? 32 : (i ? 4 : 8);

		if (image->stride[i] < row || image->stride[i] % unit ||
		    image->stride[i] / unit > 1023 ||
		    (i == 2 && image->stride[2] != image->stride[1]))
			return -EINVAL;
		ret = ge_import(ge, job, first, image->fd[i], image->offset[i],
				(u64)image->stride[i] * rows, output, addresses + i);
		if (ret)
			return ret;
	}
	/* Planes may share one DMA-BUF, but their storage must not overlap. */
	for (i = first; i < job->used; i++) {
		unsigned int j;

		for (j = first; j < i; j++)
			if (ge_overlaps(&job->maps[i], &job->maps[j]))
				return -EINVAL;
	}
	return 0;
}

static u32 ge_stride(const struct ar_ge2d_image *image)
{
	if (image->format == AR_GE2D_ARGB8888)
		return image->stride[0] / 32;
	return image->stride[0] / 8 | ((image->stride[1] / 4) << 16);
}

static u32 *ge_bitmap(u32 *cmd, const struct ar_ge2d_image *image,
		     const u32 *addresses, u32 sx, u32 sy,
		     u32 dx, u32 dy, u32 width, u32 height)
{
	bool yuv = image->format == AR_GE2D_YUV420;

	/* YUV is opaque; ARGB uses each pixel's straight alpha. */
	*cmd++ = yuv ? 0xa3fe23a3 : 0xa3fe00a3;
	*cmd++ = (GE_CSC_709_LIMITED << 29) | 0x2000 | dx | (dy << 16);
	*cmd++ = (dx + width - 1) | ((dy + height - 1) << 16);
	*cmd++ = (sx + width - 1) | ((sy + height - 1) << 16);
	*cmd++ = ge_stride(image);
	*cmd++ = sx | (sy << 16);
	*cmd++ = addresses[0];
	if (yuv) {
		*cmd++ = addresses[1];
		*cmd++ = addresses[2];
	}
	return cmd;
}

static int ge_compose(struct ge_device *ge, const struct ar_ge2d_compose *request)
{
	struct ge_job *job;
	u32 source[3], target[3], overlay[3];
	u32 *cmd = ge->commands;
	unsigned int i, j;
	int ret;

	if (ge->poisoned)
		return -EIO;
	if (request->version != AR_GE2D_ABI_VERSION || request->flags ||
	    request->reserved || request->count > AR_GE2D_MAX_OVERLAYS ||
	    request->video.format != AR_GE2D_YUV420 ||
	    request->output.format != AR_GE2D_YUV420 ||
	    request->video.width != request->output.width ||
	    request->video.height != request->output.height)
		return -EINVAL;
	job = kzalloc(sizeof(*job), GFP_KERNEL);
	if (!job)
		return -ENOMEM;
	ret = ge_image(ge, job, &request->video, false, source);
	if (ret)
		goto out;
	ret = ge_image(ge, job, &request->output, true, target);
	if (ret)
		goto out;
	*cmd++ = 0xa1ff13a1; /* planar YUV, BT.709 limited, no auxiliary table */
	*cmd++ = (request->output.width - 1) | ((request->output.height - 1) << 16);
	*cmd++ = ge_stride(&request->output);
	for (i = 0; i < 3; i++)
		*cmd++ = target[i];
	cmd = ge_bitmap(cmd, &request->video, source, 0, 0, 0, 0,
			request->video.width, request->video.height);
	for (i = 0; i < request->count; i++) {
		const struct ar_ge2d_overlay *o = &request->overlays[i];

		if (o->image.format != AR_GE2D_ARGB8888 || !o->width || !o->height ||
		    o->src_x > o->image.width || o->src_y > o->image.height ||
		    o->width > o->image.width - o->src_x ||
		    o->height > o->image.height - o->src_y ||
		    o->dst_x > request->output.width || o->dst_y > request->output.height ||
		    o->width > request->output.width - o->dst_x ||
		    o->height > request->output.height - o->dst_y) {
			ret = -EINVAL;
			goto out;
		}
		ret = ge_image(ge, job, &o->image, false, overlay);
		if (ret)
			goto out;
		cmd = ge_bitmap(cmd, &o->image, overlay, o->src_x, o->src_y,
				o->dst_x, o->dst_y, o->width, o->height);
	}
	/* Never overwrite decoder references or read HUD from the write target. */
	for (i = 3; i < 6; i++)
		for (j = 0; j < job->used; j++)
			if ((j < 3 || j >= 6) &&
			    (job->maps[i].buf == job->maps[j].buf ||
			     ge_overlaps(&job->maps[i], &job->maps[j]))) {
				ret = -EINVAL;
				goto out;
			}
	*cmd++ = 0xa50001a5;
	ret = ge_initialize(ge);
	if (ret)
		goto out;
	reinit_completion(&ge->done);
	ge->status = 0;
	ge->completed = 0x100;
	ge->sequence = (ge->sequence + 1) & 31;
	writel(0xffff, ge->regs + 0x0c);
	writel((readl(ge->regs + 0xbc) & ~0x1ffff) | 0x8200, ge->regs + 0xbc);
	dma_wmb();
	writel(ge->commands_dma, ge->regs + 0x1c);
	writel(ge->commands_dma + (cmd - ge->commands - 1) * 4, ge->regs + 0x20);
	writel(ge->sequence, ge->regs + 0x24);
	ret = wait_for_completion_timeout(&ge->done, msecs_to_jiffies(500)) ? 0 : -ETIMEDOUT;
	if (!ret && ((ge->status & 0x1fc0) ||
		     (ge->completed & 0x1ff) != ge->sequence))
		ret = -EIO;
	if (ret) {
		/* Reset/abort semantics are not verified. Fail closed: keep every
		 * DMA mapping alive, block further work, and require a reboot.
		 */
		ge->poisoned = true;
		ge->retained = job;
		__module_get(THIS_MODULE);
		writel(readl(ge->regs + 8) | 0xffff, ge->regs + 8);
		dev_err(ge->dev, "composition failed (%d, irq=%x frame=%x); buffers retained until reboot\n",
			ret, ge->status, ge->completed);
		return ret;
	}
	dma_rmb();
out:
	ge_unmap(job);
	kfree(job);
	return ret;
}

static int ge_open(struct inode *inode, struct file *file)
{
	struct ge_device *ge = container_of(file->private_data, struct ge_device, misc);

	if (!capable(CAP_SYS_RAWIO))
		return -EPERM;
	if (atomic_cmpxchg(&ge->opened, 0, 1))
		return -EBUSY;
	file->private_data = ge;
	/* A display modeset pulses the shared DC reset (0x600), which can clear
	 * this engine's setup: set it up again for every new user (one export).
	 * The interrupt handler stays armed meanwhile.
	 */
	mutex_lock(&ge->lock);
	ge->stale = true;
	mutex_unlock(&ge->lock);
	return 0;
}
static int ge_release(struct inode *inode, struct file *file)
{
	struct ge_device *ge = file->private_data;

	atomic_set(&ge->opened, 0);
	return 0;
}
static long ge_ioctl(struct file *file, unsigned int command, unsigned long arg)
{
	struct ge_device *ge = file->private_data;
	struct ar_ge2d_compose *request;
	const struct ar_ge2d_caps caps = { AR_GE2D_ABI_VERSION, GE_WIDTH,
		GE_HEIGHT, AR_GE2D_MAX_OVERLAYS };
	int ret;

	if (!capable(CAP_SYS_RAWIO))
		return -EPERM;
	if (command == AR_GE2D_GET_CAPS)
		return copy_to_user((void __user *)arg, &caps, sizeof(caps)) ? -EFAULT : 0;
	if (command != AR_GE2D_COMPOSE)
		return -ENOTTY;
	request = memdup_user((void __user *)arg, sizeof(*request));
	if (IS_ERR(request))
		return PTR_ERR(request);
	ret = mutex_lock_interruptible(&ge->lock);
	if (!ret) {
		ret = ge_compose(ge, request);
		mutex_unlock(&ge->lock);
	}
	kfree(request);
	return ret;
}
static const struct file_operations ge_fops = {
	.owner = THIS_MODULE,
	.open = ge_open,
	.release = ge_release,
	.unlocked_ioctl = ge_ioctl,
	.compat_ioctl = compat_ptr_ioctl,
};

static int ge_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct ge_device *ge;
	int irq, ret;

	ge = devm_kzalloc(dev, sizeof(*ge), GFP_KERNEL);
	if (!ge)
		return -ENOMEM;
	ge->dev = dev;
	mutex_init(&ge->lock);
	init_completion(&ge->done);
	atomic_set(&ge->opened, 0);
	ge->regs = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(ge->regs))
		return PTR_ERR(ge->regs);
	ge->crg = syscon_regmap_lookup_by_phandle(dev->of_node, "artosyn,dc-syscon");
	if (IS_ERR(ge->crg))
		return PTR_ERR(ge->crg);
	ret = dma_set_mask_and_coherent(dev, DMA_BIT_MASK(32));
	if (ret)
		return ret;
	ge->commands = dma_alloc_coherent(dev, GE_COMMAND_BYTES,
					 &ge->commands_dma, GFP_KERNEL);
	if (!ge->commands)
		return -ENOMEM;
	irq = platform_get_irq(pdev, 0);
	if (irq < 0) {
		ret = irq;
		goto free_commands;
	}
	ret = devm_request_irq(dev, irq, ge_irq, 0, dev_name(dev), ge);
	if (ret)
		goto free_commands;
	ge->misc = (struct miscdevice) {
		.minor = MISC_DYNAMIC_MINOR, .name = "ar9311-ge2d",
		.fops = &ge_fops, .mode = 0600, .parent = dev,
	};
	ret = misc_register(&ge->misc);
	if (ret)
		goto free_commands;
	platform_set_drvdata(pdev, ge);
	return 0;
free_commands:
	dma_free_coherent(dev, GE_COMMAND_BYTES, ge->commands, ge->commands_dma);
	return ret;
}
static void ge_remove(struct platform_device *pdev)
{
	struct ge_device *ge = platform_get_drvdata(pdev);

	misc_deregister(&ge->misc);
	if (ge->initialized) {
		writel(readl(ge->regs + 8) | 0xffff, ge->regs + 8);
		writel(0xffff, ge->regs + 0x0c);
	}
	dma_free_coherent(ge->dev, GE_COMMAND_BYTES, ge->commands, ge->commands_dma);
}
static const struct of_device_id ge_match[] = {
	{ .compatible = "artosyn,ar9311-ge2d" }, { }
};
MODULE_DEVICE_TABLE(of, ge_match);
static struct platform_driver ge_driver = {
	.probe = ge_probe,
	.remove = ge_remove,
	.driver = { .name = "ar9311-ge2d", .of_match_table = ge_match,
		.suppress_bind_attrs = true },
};
module_platform_driver(ge_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("AR9311 DMA-BUF video/HUD compositor");
MODULE_IMPORT_NS("DMA_BUF");
