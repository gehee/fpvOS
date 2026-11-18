// SPDX-License-Identifier: GPL-2.0-only
/* SmartSens SC231AI RAW10: 1920x1080 at up to 60 fps, and its centre 720
 * rows, 1920x720, at up to 90 fps (sc231ai-mode.h).
 * Controller-independent sensor driver; board wiring belongs in firmware.
 */
#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/pm_runtime.h>
#include <media/v4l2-async.h>
#include <media/v4l2-ctrls.h>
#include <media/v4l2-fwnode.h>
#include <media/v4l2-subdev.h>
#include "sc231ai-mode.h"
#include "sc231ai-gain.h"

#define SC231AI_CODE MEDIA_BUS_FMT_SBGGR10_1X10
#define SC231AI_HTS 2240
#define SC231AI_PIXEL_RATE 151200000
#define SC231AI_MCLK 24000000
/* Exposure stays this many lines short of the frame, as in stock 1080p60. */
#define SC231AI_EXPOSURE_MARGIN 11
/* Rows of vertical blanking a frame keeps at least: 1080p60 has 45, 720p90
 * 30 (it reads 8 rows above its output, like 1080p).
 */
#define SC231AI_MIN_VBLANK 30
#define SC231AI_MAX_VTS 0x7fff

static const s64 sc231ai_link_frequencies[] = { 378000000 };

/* The mode the sensor starts in, for a pipeline that sets no format:
 * 1080p60, 1080p50, 1080p30, 720p90 or 720p60.
 */
static char *mode = "1080p60";
module_param(mode, charp, 0444);
MODULE_PARM_DESC(mode, "initial mode, <height>p<fps> (default 1080p60)");

struct sc231ai_mode {
	unsigned int width, height;
	const struct sc231ai_reg *regs;	/* written after sc231ai_1080p60 */
	unsigned int nregs;
	unsigned int fps[4];		/* fastest first; 0 ends the list */
};

static const struct sc231ai_mode sc231ai_modes[] = {
	{ 1920, 1080, NULL, 0, { 60, 50, 30 } },
	{ 1920, 720, sc231ai_720p, ARRAY_SIZE(sc231ai_720p), { 90, 60 } },
};

/* The frame length for a rate, as stock stretches its one mode: the pixel
 * rate over the line length and the rate. 0 if the rate does not fit.
 */
static unsigned int sc231ai_mode_vts(const struct sc231ai_mode *m, unsigned int fps)
{
	unsigned int vts;

	if (!fps)
		return 0;
	vts = DIV_ROUND_CLOSEST(SC231AI_PIXEL_RATE, SC231AI_HTS * fps);
	return vts >= m->height + SC231AI_MIN_VBLANK && vts <= SC231AI_MAX_VTS ? vts : 0;
}

struct sc231ai {
	struct v4l2_subdev sd;
	struct media_pad pad;
	struct v4l2_ctrl_handler controls;
	struct v4l2_ctrl *exposure_cluster[3];
	struct v4l2_ctrl *hflip, *vflip;
	struct v4l2_ctrl *hblank, *vblank;
	const struct sc231ai_mode *mode;
	unsigned int fps;
	struct mutex lock;
	struct clk *mclk;
	struct gpio_desc *reset;
	struct gpio_desc *powerdown;
	bool streaming;
};

static struct sc231ai *to_sc231ai(struct v4l2_subdev *sd)
{
	return container_of(sd, struct sc231ai, sd);
}

static int sc231ai_write(struct sc231ai *sensor, u16 address, u8 value)
{
	struct i2c_client *client = v4l2_get_subdevdata(&sensor->sd);
	u8 bytes[] = { address >> 8, address & 0xff, value };
	int ret = i2c_master_send(client, bytes, sizeof(bytes));

	return ret == sizeof(bytes) ? 0 : ret < 0 ? ret : -EIO;
}

static int sc231ai_read(struct sc231ai *sensor, u16 address)
{
	struct i2c_client *client = v4l2_get_subdevdata(&sensor->sd);
	u8 bytes[] = { address >> 8, address & 0xff }, value;
	struct i2c_msg messages[] = {
		{ .addr = client->addr, .len = 2, .buf = bytes },
		{ .addr = client->addr, .flags = I2C_M_RD, .len = 1, .buf = &value },
	};
	int ret = i2c_transfer(client->adapter, messages, ARRAY_SIZE(messages));

	return ret == ARRAY_SIZE(messages) ? value : ret < 0 ? ret : -EIO;
}

static int sc231ai_resume(struct device *dev)
{
	struct sc231ai *sensor = to_sc231ai(dev_get_drvdata(dev));
	int ret;

	gpiod_set_value_cansleep(sensor->reset, 1);
	gpiod_set_value_cansleep(sensor->powerdown, 0);
	ret = clk_prepare_enable(sensor->mclk);
	if (ret) {
		gpiod_set_value_cansleep(sensor->powerdown, 1);
		return ret;
	}
	gpiod_set_value_cansleep(sensor->reset, 0);
	usleep_range(10000, 11000);
	return 0;
}

static int sc231ai_suspend(struct device *dev)
{
	struct sc231ai *sensor = to_sc231ai(dev_get_drvdata(dev));

	gpiod_set_value_cansleep(sensor->reset, 1);
	clk_disable_unprepare(sensor->mclk);
	gpiod_set_value_cansleep(sensor->powerdown, 1);
	return 0;
}

static int sc231ai_set_control(struct v4l2_ctrl *ctrl)
{
	struct sc231ai *sensor = container_of(ctrl->handler, struct sc231ai, controls);
	struct device *dev = sensor->sd.dev;
	unsigned int half_lines;
	u8 again, afine, dgain, dfine;
	int ret = 0, release;

	if (ctrl->id != V4L2_CID_EXPOSURE && ctrl->id != V4L2_CID_HFLIP &&
	    ctrl->id != V4L2_CID_VFLIP)
		return -EINVAL;
	ret = pm_runtime_get_if_in_use(dev);
	if (ret <= 0)
		return ret;

	/* Mirror is bits 2:1 of 0x3221, flip bits 6:5. The sensor keeps its
	 * BGGR phase in all four combinations (P1 bench, 2026-11-04: colour
	 * and edges checked in each), so the bus format does not change.
	 */
	if (ctrl->id != V4L2_CID_EXPOSURE) {
		ret = sc231ai_write(sensor, 0x3221, (sensor->hflip->val ? 0x06 : 0) |
						    (sensor->vflip->val ? 0x60 : 0));
		pm_runtime_put(dev);
		return ret;
	}

	/* Exposure is a 20-bit half-line count. Hold the register group so
	 * an update cannot straddle two frames; always release after errors.
	 */
	half_lines = sensor->exposure_cluster[0]->val * 2;
	sc231ai_analogue_gain(sensor->exposure_cluster[1]->val, &again, &afine);
	sc231ai_digital_gain(sensor->exposure_cluster[2]->val, &dgain, &dfine);
	ret = sc231ai_write(sensor, 0x3812, 0x00);
	if (!ret)
		ret = sc231ai_write(sensor, 0x3e00, half_lines >> 12);
	if (!ret)
		ret = sc231ai_write(sensor, 0x3e01, half_lines >> 4);
	if (!ret)
		ret = sc231ai_write(sensor, 0x3e02, half_lines << 4);
	if (!ret)
		ret = sc231ai_write(sensor, 0x3e08, again);
	if (!ret)
		ret = sc231ai_write(sensor, 0x3e09, afine);
	if (!ret)
		ret = sc231ai_write(sensor, 0x3e06, dgain);
	if (!ret)
		ret = sc231ai_write(sensor, 0x3e07, dfine);
	release = sc231ai_write(sensor, 0x3812, 0x30);
	pm_runtime_put(dev);
	return ret ? ret : release;
}

static const struct v4l2_ctrl_ops sc231ai_control_ops = {
	.s_ctrl = sc231ai_set_control,
};

/* Line and frame length: 0x320c/0x320d and 0x320e/0x320f. */
static int sc231ai_write_timing(struct sc231ai *sensor)
{
	unsigned int hts = SC231AI_HTS;
	unsigned int vts = sc231ai_mode_vts(sensor->mode, sensor->fps);
	int ret;

	ret = sc231ai_write(sensor, 0x320c, hts >> 8);
	if (!ret)
		ret = sc231ai_write(sensor, 0x320d, hts & 0xff);
	if (!ret)
		ret = sc231ai_write(sensor, 0x320e, vts >> 8);
	if (!ret)
		ret = sc231ai_write(sensor, 0x320f, vts & 0xff);
	if (!ret)
		dev_info(sensor->sd.dev, "%ux%u at %u fps: line %u, frame %u\n",
			 sensor->mode->width, sensor->mode->height, sensor->fps,
			 hts, vts);
	return ret;
}

/* Blanking and the exposure limit follow the mode. Called with the lock. */
static int sc231ai_update_limits(struct sc231ai *sensor)
{
	const struct sc231ai_mode *m = sensor->mode;
	unsigned int hblank = SC231AI_HTS - m->width;
	unsigned int vts = sc231ai_mode_vts(m, sensor->fps);
	unsigned int vblank = vts - m->height;
	int ret;

	ret = __v4l2_ctrl_modify_range(sensor->hblank, hblank, hblank, 1, hblank);
	if (!ret)
		ret = __v4l2_ctrl_modify_range(sensor->vblank, vblank, vblank, 1, vblank);
	if (!ret)
		ret = __v4l2_ctrl_modify_range(sensor->exposure_cluster[0], 1,
					       vts - SC231AI_EXPOSURE_MARGIN, 1,
					       vts - SC231AI_EXPOSURE_MARGIN);
	return ret;
}

static int sc231ai_stream(struct v4l2_subdev *sd, int enable)
{
	struct sc231ai *sensor = to_sc231ai(sd);
	unsigned int i;
	int ret = 0;

	mutex_lock(&sensor->lock);
	if (sensor->streaming == !!enable)
		goto unlock;
	if (!enable) {
		ret = sc231ai_write(sensor, 0x0100, 0);
		sensor->streaming = false;
		/* Synchronous suspend also asserts reset if standby failed. */
		pm_runtime_put_sync(sd->dev);
		goto unlock;
	}
	ret = pm_runtime_resume_and_get(sd->dev);
	if (ret < 0)
		goto unlock;
	for (i = 0; i < ARRAY_SIZE(sc231ai_1080p60); i++) {
		ret = sc231ai_write(sensor, sc231ai_1080p60[i].address,
				    sc231ai_1080p60[i].value);
		if (ret)
			goto power_off;
		if (sc231ai_1080p60[i].address == 0x0103)
			usleep_range(1000, 2000);
	}
	for (i = 0; i < sensor->mode->nregs; i++) {
		ret = sc231ai_write(sensor, sensor->mode->regs[i].address,
				    sensor->mode->regs[i].value);
		if (ret)
			goto power_off;
	}
	ret = sc231ai_write_timing(sensor);
	if (ret)
		goto power_off;
	ret = __v4l2_ctrl_handler_setup(&sensor->controls);
	if (ret)
		goto power_off;
	ret = sc231ai_write(sensor, 0x0100, 1);
	if (ret)
		goto power_off;
	sensor->streaming = true;
	goto unlock;
power_off:
	sc231ai_write(sensor, 0x0100, 0);
	pm_runtime_put_sync(sd->dev);
unlock:
	mutex_unlock(&sensor->lock);
	return ret;
}

static void sc231ai_format(const struct sc231ai_mode *m,
			   struct v4l2_mbus_framefmt *fmt)
{
	*fmt = (struct v4l2_mbus_framefmt) {
		.width = m->width, .height = m->height,
		.code = SC231AI_CODE, .field = V4L2_FIELD_NONE,
		.colorspace = V4L2_COLORSPACE_RAW,
		.quantization = V4L2_QUANTIZATION_FULL_RANGE,
		.xfer_func = V4L2_XFER_FUNC_NONE,
	};
}

static int sc231ai_init_state(struct v4l2_subdev *sd,
			      struct v4l2_subdev_state *state)
{
	sc231ai_format(to_sc231ai(sd)->mode, v4l2_subdev_state_get_format(state, 0));
	return 0;
}

static int sc231ai_set_format(struct v4l2_subdev *sd,
			      struct v4l2_subdev_state *state,
			      struct v4l2_subdev_format *fmt)
{
	struct sc231ai *sensor = to_sc231ai(sd);
	const struct sc231ai_mode *m;

	if (fmt->pad)
		return -EINVAL;
	m = v4l2_find_nearest_size(sc231ai_modes, ARRAY_SIZE(sc231ai_modes),
				   width, height, fmt->format.width,
				   fmt->format.height);
	sc231ai_format(m, &fmt->format);
	if (fmt->which == V4L2_SUBDEV_FORMAT_ACTIVE) {
		if (sensor->streaming)
			return -EBUSY;
		if (m != sensor->mode) {
			int ret;

			sensor->mode = m;
			sensor->fps = m->fps[0];
			ret = sc231ai_update_limits(sensor);
			if (ret)
				return ret;
		}
	}
	*v4l2_subdev_state_get_format(state, 0) = fmt->format;
	return 0;
}

static int sc231ai_enum_code(struct v4l2_subdev *sd,
			    struct v4l2_subdev_state *state,
			    struct v4l2_subdev_mbus_code_enum *code)
{
	if (code->pad || code->index)
		return -EINVAL;
	code->code = SC231AI_CODE;
	return 0;
}

static int sc231ai_enum_size(struct v4l2_subdev *sd,
			    struct v4l2_subdev_state *state,
			    struct v4l2_subdev_frame_size_enum *size)
{
	if (size->pad || size->index >= ARRAY_SIZE(sc231ai_modes) ||
	    size->code != SC231AI_CODE)
		return -EINVAL;
	size->min_width = size->max_width = sc231ai_modes[size->index].width;
	size->min_height = size->max_height = sc231ai_modes[size->index].height;
	return 0;
}

static int sc231ai_get_interval(struct v4l2_subdev *sd,
			       struct v4l2_subdev_state *state,
			       struct v4l2_subdev_frame_interval *interval)
{
	struct sc231ai *sensor = to_sc231ai(sd);

	if (interval->pad || interval->stream)
		return -EINVAL;
	interval->interval = (struct v4l2_fract) { 1, sensor->fps };
	return 0;
}

/* The mode's rate nearest the one asked for; the rest of its list is the
 * frame stretched, as stock does for lower rates.
 */
static int sc231ai_set_interval(struct v4l2_subdev *sd,
			       struct v4l2_subdev_state *state,
			       struct v4l2_subdev_frame_interval *interval)
{
	struct sc231ai *sensor = to_sc231ai(sd);
	const struct sc231ai_mode *m = sensor->mode;
	unsigned int want, best = 0, i;

	if (interval->pad || interval->stream)
		return -EINVAL;
	if (interval->which == V4L2_SUBDEV_FORMAT_TRY)
		m = v4l2_find_nearest_size(sc231ai_modes, ARRAY_SIZE(sc231ai_modes),
					   width, height,
					   v4l2_subdev_state_get_format(state, 0)->width,
					   v4l2_subdev_state_get_format(state, 0)->height);
	want = interval->interval.numerator ?
	       DIV_ROUND_CLOSEST(interval->interval.denominator,
				 interval->interval.numerator) : m->fps[0];
	for (i = 0; i < ARRAY_SIZE(m->fps) && m->fps[i]; i++)
		if (sc231ai_mode_vts(m, m->fps[i]) &&
		    (!best || abs((int)m->fps[i] - (int)want) < abs((int)best - (int)want)))
			best = m->fps[i];
	if (!best)
		return -EINVAL;
	interval->interval = (struct v4l2_fract) { 1, best };
	if (interval->which == V4L2_SUBDEV_FORMAT_TRY)
		return 0;
	if (sensor->streaming)
		return best == sensor->fps ? 0 : -EBUSY;
	sensor->fps = best;
	return sc231ai_update_limits(sensor);
}

static int sc231ai_enum_interval(struct v4l2_subdev *sd,
				struct v4l2_subdev_state *state,
				struct v4l2_subdev_frame_interval_enum *interval)
{
	const struct sc231ai_mode *m = NULL;
	unsigned int i, n = 0;

	if (interval->pad || interval->stream || interval->code != SC231AI_CODE)
		return -EINVAL;
	for (i = 0; i < ARRAY_SIZE(sc231ai_modes); i++)
		if (interval->width == sc231ai_modes[i].width &&
		    interval->height == sc231ai_modes[i].height)
			m = &sc231ai_modes[i];
	if (!m)
		return -EINVAL;
	for (i = 0; i < ARRAY_SIZE(m->fps) && m->fps[i]; i++) {
		if (!sc231ai_mode_vts(m, m->fps[i]))
			continue;
		if (n++ == interval->index) {
			interval->interval = (struct v4l2_fract) { 1, m->fps[i] };
			return 0;
		}
	}
	return -EINVAL;
}

static const struct v4l2_subdev_pad_ops sc231ai_pad_ops = {
	.enum_mbus_code = sc231ai_enum_code,
	.enum_frame_size = sc231ai_enum_size,
	.enum_frame_interval = sc231ai_enum_interval,
	.get_frame_interval = sc231ai_get_interval,
	.set_frame_interval = sc231ai_set_interval,
	.get_fmt = v4l2_subdev_get_fmt,
	.set_fmt = sc231ai_set_format,
};
static const struct v4l2_subdev_video_ops sc231ai_video_ops = {
	.s_stream = sc231ai_stream,
};
static const struct v4l2_subdev_ops sc231ai_ops = {
	.pad = &sc231ai_pad_ops,
	.video = &sc231ai_video_ops,
};
static const struct v4l2_subdev_internal_ops sc231ai_internal_ops = {
	.init_state = sc231ai_init_state,
};

static int sc231ai_endpoint(struct device *dev)
{
	struct v4l2_fwnode_endpoint ep = { .bus_type = V4L2_MBUS_CSI2_DPHY };
	struct fwnode_handle *node;
	unsigned int i;
	int ret;

	node = fwnode_graph_get_next_endpoint(dev_fwnode(dev), NULL);
	if (!node)
		return -EINVAL;
	ret = v4l2_fwnode_endpoint_alloc_parse(node, &ep);
	fwnode_handle_put(node);
	if (ret)
		goto free;
	ret = -EINVAL;
	if (ep.bus.mipi_csi2.clock_lane != 0 ||
	    ep.bus.mipi_csi2.num_data_lanes != 2 ||
	    ep.bus.mipi_csi2.data_lanes[0] != 1 ||
	    ep.bus.mipi_csi2.data_lanes[1] != 2)
		goto free;
	for (i = 0; i < ep.nr_of_link_frequencies; i++)
		if (ep.link_frequencies[i] == sc231ai_link_frequencies[0])
			ret = 0;
free:
	v4l2_fwnode_endpoint_free(&ep);
	return ret;
}

/* The mode parameter: <height>p<fps>, a size and one of its rates. */
static int sc231ai_parse_mode(struct sc231ai *sensor)
{
	unsigned int height, fps, i, j;

	if (sscanf(mode, "%up%u", &height, &fps) != 2)
		return -EINVAL;
	for (i = 0; i < ARRAY_SIZE(sc231ai_modes); i++)
		for (j = 0; j < ARRAY_SIZE(sc231ai_modes[i].fps); j++)
			if (sc231ai_modes[i].height == height &&
			    sc231ai_modes[i].fps[j] == fps &&
			    sc231ai_mode_vts(&sc231ai_modes[i], fps)) {
				sensor->mode = &sc231ai_modes[i];
				sensor->fps = fps;
				return 0;
			}
	return -EINVAL;
}

static int sc231ai_probe(struct i2c_client *client)
{
	struct device *dev = &client->dev;
	struct sc231ai *sensor;
	struct v4l2_ctrl *ctrl;
	unsigned int hblank, vts;
	int ret, hi, lo;

	if (!i2c_check_functionality(client->adapter, I2C_FUNC_I2C))
		return -EOPNOTSUPP;
	ret = sc231ai_endpoint(dev);
	if (ret)
		return dev_err_probe(dev, ret, "requires 2 lanes at 378 MHz\n");
	sensor = devm_kzalloc(dev, sizeof(*sensor), GFP_KERNEL);
	if (!sensor)
		return -ENOMEM;
	ret = sc231ai_parse_mode(sensor);
	if (ret)
		return dev_err_probe(dev, ret, "mode %s: not a mode this sensor has\n", mode);
	mutex_init(&sensor->lock);
	v4l2_i2c_subdev_init(&sensor->sd, client, &sc231ai_ops);
	sensor->sd.internal_ops = &sc231ai_internal_ops;
	sensor->sd.state_lock = &sensor->lock;
	sensor->sd.flags |= V4L2_SUBDEV_FL_HAS_DEVNODE;
	sensor->sd.entity.function = MEDIA_ENT_F_CAM_SENSOR;
	sensor->pad.flags = MEDIA_PAD_FL_SOURCE;
	sensor->mclk = devm_clk_get(dev, "xclk");
	if (IS_ERR(sensor->mclk))
		return dev_err_probe(dev, PTR_ERR(sensor->mclk), "missing xclk\n");
	if (clk_get_rate(sensor->mclk) != SC231AI_MCLK)
		return dev_err_probe(dev, -EINVAL, "requires 24 MHz xclk\n");
	sensor->reset = devm_gpiod_get(dev, "reset", GPIOD_OUT_HIGH);
	if (IS_ERR(sensor->reset))
		return dev_err_probe(dev, PTR_ERR(sensor->reset), "missing reset\n");
	sensor->powerdown = devm_gpiod_get_optional(dev, "powerdown", GPIOD_OUT_HIGH);
	if (IS_ERR(sensor->powerdown))
		return dev_err_probe(dev, PTR_ERR(sensor->powerdown), "powerdown GPIO\n");
	ret = sc231ai_resume(dev);
	if (ret)
		return ret;
	hi = sc231ai_read(sensor, 0x3107);
	lo = sc231ai_read(sensor, 0x3108);
	sc231ai_suspend(dev);
	if (hi < 0 || lo < 0)
		return hi < 0 ? hi : lo;
	if (((hi << 8) | lo) != 0xcb6a)
		return dev_err_probe(dev, -ENODEV, "unexpected sensor ID %02x%02x\n", hi, lo);

	v4l2_ctrl_handler_init(&sensor->controls, 9);
	sensor->controls.lock = &sensor->lock;
	ctrl = v4l2_ctrl_new_int_menu(&sensor->controls, NULL, V4L2_CID_LINK_FREQ,
				    0, 0, sc231ai_link_frequencies);
	if (ctrl)
		ctrl->flags |= V4L2_CTRL_FLAG_READ_ONLY;
	v4l2_ctrl_new_std(&sensor->controls, NULL, V4L2_CID_PIXEL_RATE,
			 SC231AI_PIXEL_RATE, SC231AI_PIXEL_RATE, 1, SC231AI_PIXEL_RATE);
	hblank = SC231AI_HTS - sensor->mode->width;
	vts = sc231ai_mode_vts(sensor->mode, sensor->fps);
	sensor->hblank = v4l2_ctrl_new_std(&sensor->controls, NULL, V4L2_CID_HBLANK,
					   hblank, hblank, 1, hblank);
	if (sensor->hblank)
		sensor->hblank->flags |= V4L2_CTRL_FLAG_READ_ONLY;
	sensor->vblank = v4l2_ctrl_new_std(&sensor->controls, NULL, V4L2_CID_VBLANK,
					   vts - sensor->mode->height,
					   vts - sensor->mode->height, 1,
					   vts - sensor->mode->height);
	if (sensor->vblank)
		sensor->vblank->flags |= V4L2_CTRL_FLAG_READ_ONLY;
	sensor->exposure_cluster[0] = v4l2_ctrl_new_std(&sensor->controls,
		&sc231ai_control_ops, V4L2_CID_EXPOSURE,
		1, vts - SC231AI_EXPOSURE_MARGIN, 1, vts - SC231AI_EXPOSURE_MARGIN);
	sensor->exposure_cluster[1] = v4l2_ctrl_new_std(&sensor->controls,
		&sc231ai_control_ops, V4L2_CID_ANALOGUE_GAIN, 0, 219, 1, 0);
	sensor->exposure_cluster[2] = v4l2_ctrl_new_std(&sensor->controls,
		&sc231ai_control_ops, V4L2_CID_DIGITAL_GAIN, 0, 127, 1, 0);
	sensor->hflip = v4l2_ctrl_new_std(&sensor->controls, &sc231ai_control_ops,
					  V4L2_CID_HFLIP, 0, 1, 1, 0);
	sensor->vflip = v4l2_ctrl_new_std(&sensor->controls, &sc231ai_control_ops,
					  V4L2_CID_VFLIP, 0, 1, 1, 0);
	ret = sensor->controls.error;
	if (ret)
		goto controls;
	v4l2_ctrl_cluster(ARRAY_SIZE(sensor->exposure_cluster),
			  sensor->exposure_cluster);
	sensor->sd.ctrl_handler = &sensor->controls;
	ret = media_entity_pads_init(&sensor->sd.entity, 1, &sensor->pad);
	if (ret)
		goto controls;
	ret = v4l2_subdev_init_finalize(&sensor->sd);
	if (ret)
		goto entity;
	pm_runtime_set_suspended(dev);
	pm_runtime_enable(dev);
	ret = v4l2_async_register_subdev_sensor(&sensor->sd);
	if (!ret)
		return 0;
	pm_runtime_disable(dev);
	v4l2_subdev_cleanup(&sensor->sd);
entity:
	media_entity_cleanup(&sensor->sd.entity);
controls:
	v4l2_ctrl_handler_free(&sensor->controls);
	return ret;
}

static void sc231ai_remove(struct i2c_client *client)
{
	struct v4l2_subdev *sd = i2c_get_clientdata(client);
	struct sc231ai *sensor = to_sc231ai(sd);

	v4l2_async_unregister_subdev(sd);
	pm_runtime_disable(&client->dev);
	if (!pm_runtime_status_suspended(&client->dev))
		sc231ai_suspend(&client->dev);
	pm_runtime_set_suspended(&client->dev);
	v4l2_subdev_cleanup(sd);
	media_entity_cleanup(&sd->entity);
	v4l2_ctrl_handler_free(&sensor->controls);
	mutex_destroy(&sensor->lock);
}

static const struct dev_pm_ops sc231ai_pm_ops = {
	SET_RUNTIME_PM_OPS(sc231ai_suspend, sc231ai_resume, NULL)
};
static const struct of_device_id sc231ai_of_match[] = {
	{ .compatible = "smartsens,sc231ai" },
	{ }
};
MODULE_DEVICE_TABLE(of, sc231ai_of_match);
static struct i2c_driver sc231ai_driver = {
	.driver = {
		.name = "sc231ai",
		.of_match_table = sc231ai_of_match,
		.pm = &sc231ai_pm_ops,
	},
	.probe = sc231ai_probe,
	.remove = sc231ai_remove,
};
module_i2c_driver(sc231ai_driver);
MODULE_DESCRIPTION("SmartSens SC231AI RAW10 sensor, 1080p and its centre 720 rows");
MODULE_LICENSE("GPL");
