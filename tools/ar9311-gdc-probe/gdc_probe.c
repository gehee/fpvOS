// SPDX-License-Identifier: GPL-2.0-or-later
/* Isolated AR9311 GDC experiment. Root only, fixed owned buffers, no raw DMA ABI. */
#include <linux/module.h>
#include <linux/io.h>
#include <linux/ioport.h>
#include <linux/dma-mapping.h>
#include <linux/platform_device.h>
#include <linux/miscdevice.h>
#include <linux/debugfs.h>
#include <linux/seq_file.h>
#include <linux/uaccess.h>
#include <linux/delay.h>
#include <linux/iopoll.h>
#include <linux/ktime.h>
#include <linux/mutex.h>
#include <linux/mm.h>
#include <linux/of.h>
#include "probe_abi.h"

static bool arm;
static bool cached;
module_param(cached, bool, 0400);
MODULE_PARM_DESC(cached,
		 "Cacheable DMA pages with explicit ownership synchronization");
module_param(arm, bool, 0400);
MODULE_PARM_DESC(arm, "Permit explicit INIT/RUN ioctls (default read-only)");
static void __iomem *regs, *crg, *clockregs;
static struct platform_device *pdev;
static struct dentry *dir;
static void *buf;
static dma_addr_t dma;
static bool initialized, poisoned;
static u32 saved_gate, saved_irq_mask;
static atomic_t opened = ATOMIC_INIT(0);
static DEFINE_MUTEX(lock);
#define GATE_MASK 0x4c00

static int state_show(struct seq_file *s, void *unused)
{
	unsigned int i;

	mutex_lock(&lock);
	seq_printf(s,
		   "armed=%u cached=%u initialized=%u poisoned=%u dma=%pad\n",
		   arm, cached, initialized, poisoned, &dma);
	seq_printf(
		s,
		"gate=%08x power=%08x power_status=%08x clock005c=%08x clock405c=%08x\n",
		readl(crg + 0x10), readl(crg + 0x204), readl(crg + 0x208),
		readl(clockregs + 0x5c), readl(clockregs + 0x405c));
	/* Do not read a potentially clock-gated peripheral before initialization. */
	if (!poisoned &&
	    (initialized || ((readl(crg + 0x10) & GATE_MASK) == GATE_MASK &&
			     (readl(crg + 0x208) & 0x808) == 0x808)))
		for (i = 0; i <= 0x90; i += 4)
			seq_printf(s, "%04x %08x\n", i, readl(regs + i));
	mutex_unlock(&lock);
	return 0;
}
DEFINE_SHOW_ATTRIBUTE(state);

static int gp_open(struct inode *inode, struct file *file)
{
	if (!capable(CAP_SYS_RAWIO))
		return -EPERM;
	return atomic_cmpxchg(&opened, 0, 1) ? -EBUSY : 0;
}
static int gp_release(struct inode *inode, struct file *file)
{
	atomic_set(&opened, 0);
	return 0;
}
static int gp_mmap(struct file *file, struct vm_area_struct *vma)
{
	if (!arm || !buf || vma->vm_pgoff ||
	    vma->vm_end - vma->vm_start != GP_BYTES)
		return -EINVAL;
	if (cached)
		return dma_mmap_pages(&pdev->dev, vma, GP_BYTES,
				      virt_to_page(buf));
	return dma_mmap_coherent(&pdev->dev, vma, buf, dma, GP_BYTES);
}

static int hw_init(void)
{
	u32 status;

	if (initialized)
		return 0;
	saved_gate = readl(crg + 0x10) & GATE_MASK;
	status = readl(crg + 0x208);
	/* The validated boot firmware leaves this unclaimed block powered and
	 * clocked. Require that state; this prototype does not own shared power
	 * controls and must not attempt an untested cold-start sequence.
	 */
	if (saved_gate != GATE_MASK || (status & 0x808) != 0x808)
		return -EHOSTDOWN;
	if (readl(regs + 0x8c) & 7)
		return -EBUSY;
	initialized = true;
	saved_irq_mask = readl(regs + 0x08);
	writel(1, regs + 0x80);
	/* Poll completion without enabling an unclaimed GIC interrupt. */
	writel(1, regs + 0x08);
	writel(readl(regs + 0x6c) & ~0xf, regs + 0x6c);
	writel(readl(regs + 0x80) | 2, regs + 0x80);
	writel(readl(regs + 0x0c), regs + 0x10);
	pr_info("gdc_probe: initialized state=%08x; clock sources unchanged\n",
		readl(regs + 0x8c));
	return 0;
}

static void sync_buffers(struct gp_job *j, bool cpu)
{
	unsigned int i;
	const u32 offsets[] = { GP_SRC_Y + j->src_offset,
				GP_SRC_U,
				GP_SRC_V,
				GP_DST_Y + j->dst_offset,
				GP_DST_U,
				GP_DST_V,
				GP_LUT };
	const u32 lengths[] = {
		j->sw * j->sh,
		j->sw * j->sh / 4,
		j->sw * j->sh / 4,
		j->dw * j->dh,
		j->dw * j->dh / 4,
		j->dw * j->dh / 4,
		ALIGN((ALIGN(j->dw / 64 + 1, 4) * 4) * (j->dh / 64 + 1), 64)
	};
	if (!cached)
		return;
	for (i = 0; i < ARRAY_SIZE(offsets); i++) {
		if (cpu)
			dma_sync_single_range_for_cpu(&pdev->dev, dma,
						      offsets[i],
						      lengths[i] + 64,
						      DMA_BIDIRECTIONAL);
		else
			dma_sync_single_range_for_device(&pdev->dev, dma,
							 offsets[i],
							 lengths[i] + 64,
							 DMA_BIDIRECTIONAL);
	}
}

static int run_job(struct gp_job *j)
{
	u32 ss, ds, ls, rows, x, y, status;
	u64 start;
	int ret;

	if (!initialized)
		return -EAGAIN;
	if (!j->sw || !j->sh || !j->dw || !j->dh || j->sw > 2048 ||
	    j->dw > 2048 || j->sh > 1152 || j->dh > 1152 ||
	    ((j->sw | j->dw | j->sh | j->dh) & 63))
		return -EINVAL;
	ss = j->sw;
	ds = j->dw;
	if ((j->src_offset | j->dst_offset) & 63 ||
	    ss * j->sh > GP_Y_BYTES - 256 || ds * j->dh > GP_Y_BYTES - 256 ||
	    j->src_offset > GP_Y_BYTES - ss * j->sh - 64 ||
	    j->dst_offset > GP_Y_BYTES - ds * j->dh - 64)
		return -ERANGE;
	ls = ALIGN(DIV_ROUND_UP(j->dw, 64) + 1, 4);
	rows = DIV_ROUND_UP(j->dh, 64) + 1;
	/* Validate map nodes; all source samples stay inside our source planes. */
	for (y = 0; y < rows; y++)
		for (x = 0; x <= DIV_ROUND_UP(j->dw, 64); x++) {
			u32 c = READ_ONCE(((u32 *)(buf + GP_LUT))[y * ls + x]);

			if ((c & 65535) > (j->sw - 2) * 4 ||
			    (c >> 16) > (j->sh - 2) * 4)
				return -ERANGE;
		}
	if (readl(regs + 0x8c) & 1)
		return -EBUSY;
	writel(((j->sh - 1) << 16) | (j->sw - 1), regs + 0x14);
	writel(((j->dh - 1) << 16) | (j->dw - 1), regs + 0x18);
	writel(dma + GP_SRC_Y + j->src_offset, regs + 0x24);
	writel(ss, regs + 0x28);
	writel(dma + GP_SRC_U, regs + 0x2c);
	writel(ss / 2, regs + 0x30);
	writel(dma + GP_SRC_V, regs + 0x34);
	writel(ss / 2, regs + 0x38);
	writel(dma + GP_DST_Y + j->dst_offset, regs + 0x3c);
	writel(ds, regs + 0x40);
	writel(dma + GP_DST_U, regs + 0x44);
	writel(ds / 2, regs + 0x48);
	writel(dma + GP_DST_V, regs + 0x4c);
	writel(ds / 2, regs + 0x50);
	writel(0x00920000, regs + 0x7c);
	writel(0x00000f0f, regs + 0x80);
	writel(dma + GP_LUT, regs + 0x1c);
	writel(ls * 4, regs + 0x20);
	writel(readl(regs + 0x6c) & ~0xf, regs + 0x6c);
	writel(readl(regs + 0x0c), regs + 0x10);
	sync_buffers(j, false);
	dma_wmb();
	start = ktime_get_ns();
	writel(1, regs);
	ret = readl_poll_timeout(regs + 0x0c, status, status & 1, 5, 200000);
	j->elapsed_ns = ktime_get_ns() - start;
	j->irq = status;
	j->state = readl(regs + 0x8c);
	dma_rmb();
	if (ret || (j->state & 7)) {
		/* Keep DMA memory and the module resident on failure. Never free
		 * memory while an engine with unverified reset semantics could
		 * still use it.
		 */
		poisoned = true;
		__module_get(THIS_MODULE);
		writel(readl(crg + 0x10) & ~GATE_MASK, crg + 0x10);
		pr_err("gdc_probe: stopped after error %d state=%08x irq=%08x; buffers pinned until reboot\n",
		       ret, j->state, status);
		return ret ?: -EIO;
	}
	writel(status, regs + 0x10);
	sync_buffers(j, true);
	return 0;
}

static long gp_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	struct gp_job job;
	int ret;

	if (!arm)
		return -EPERM;
	if (cmd != GP_INIT && cmd != GP_RUN)
		return -ENOTTY;
	if (cmd == GP_RUN &&
	    copy_from_user(&job, (void __user *)arg, sizeof(job)))
		return -EFAULT;
	mutex_lock(&lock);
	ret = poisoned ? -EIO : cmd == GP_INIT ? hw_init() : run_job(&job);
	mutex_unlock(&lock);
	if (cmd == GP_RUN &&
	    copy_to_user((void __user *)arg, &job, sizeof(job)))
		return -EFAULT;
	return ret;
}
static const struct file_operations gp_fops = {
	.owner = THIS_MODULE,
	.open = gp_open,
	.release = gp_release,
	.mmap = gp_mmap,
	.unlocked_ioctl = gp_ioctl,
};
static struct miscdevice misc = { .minor = MISC_DYNAMIC_MINOR,
				  .name = "gdc-probe",
				  .fops = &gp_fops,
				  .mode = 0600 };

static int __init gp_start(void)
{
	int ret;

	if (!of_machine_is_compatible("caddx,ascent-gnd485"))
		return -ENODEV;
	if (!request_mem_region(0x08848000, 0x1000, "gdc-probe"))
		return -EBUSY;
	regs = ioremap(0x08848000, 0x1000);
	crg = ioremap(0x0a106000, 0x210);
	clockregs = ioremap(0x0a100000, 0x5000);
	if (!regs || !crg || !clockregs) {
		ret = -ENOMEM;
		goto unmap;
	}
	pdev = platform_device_register_simple("gdc-probe", -1, NULL, 0);
	if (IS_ERR(pdev)) {
		ret = PTR_ERR(pdev);
		goto unmap;
	}
	ret = dma_coerce_mask_and_coherent(&pdev->dev, DMA_BIT_MASK(32));
	if (ret)
		goto unregister;
	if (arm) {
		buf = cached ? dma_alloc_noncoherent(&pdev->dev, GP_BYTES, &dma,
						     DMA_BIDIRECTIONAL,
						     GFP_KERNEL) :
			       dma_alloc_coherent(&pdev->dev, GP_BYTES, &dma,
						  GFP_KERNEL);
		if (!buf) {
			ret = -ENOMEM;
			goto unregister;
		}
	}
	ret = misc_register(&misc);
	if (ret)
		goto free_dma;
	dir = debugfs_create_dir("gdc-probe", NULL);
	debugfs_create_file("state", 0400, dir, NULL, &state_fops);
	pr_info("gdc_probe: loaded armed=%u; no hardware writes until INIT\n",
		arm);
	return 0;
free_dma:
	if (buf) {
		if (cached)
			dma_free_noncoherent(&pdev->dev, GP_BYTES, buf, dma,
					     DMA_BIDIRECTIONAL);
		else
			dma_free_coherent(&pdev->dev, GP_BYTES, buf, dma);
	}
unregister:
	platform_device_unregister(pdev);
unmap:
	if (clockregs)
		iounmap(clockregs);
	if (crg)
		iounmap(crg);
	if (regs)
		iounmap(regs);
	release_mem_region(0x08848000, 0x1000);
	return ret;
}
static void __exit gp_stop(void)
{
	debugfs_remove_recursive(dir);
	misc_deregister(&misc);
	if (initialized) {
		/* Jobs are synchronous and open files/maps hold this module. */
		writel(1, regs + 8);
		writel(readl(regs + 0x0c), regs + 0x10);
		writel(0, regs + 0x1c);
		writel(0, regs + 0x24);
		writel(0, regs + 0x2c);
		writel(0, regs + 0x34);
		writel(0, regs + 0x3c);
		writel(0, regs + 0x44);
		writel(0, regs + 0x4c);
		writel(saved_irq_mask, regs + 8);
		/* Clock/power state was not changed on the successful path. */
	}
	if (buf) {
		if (cached)
			dma_free_noncoherent(&pdev->dev, GP_BYTES, buf, dma,
					     DMA_BIDIRECTIONAL);
		else
			dma_free_coherent(&pdev->dev, GP_BYTES, buf, dma);
	}
	platform_device_unregister(pdev);
	iounmap(clockregs);
	iounmap(crg);
	iounmap(regs);
	release_mem_region(0x08848000, 0x1000);
}
module_init(gp_start);
module_exit(gp_stop);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Isolated AR9311 GDC hardware feasibility probe");
