// SPDX-License-Identifier: GPL-2.0-only
/* SmartSens SC231AI, fixed 1920x1080 RAW10 60 fps mode.
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
#define SC231AI_WIDTH 1920
#define SC231AI_HEIGHT 1080
#define SC231AI_HTS 2240
#define SC231AI_VTS 1125
#define SC231AI_PIXEL_RATE 151200000
#define SC231AI_MCLK 24000000

static const s64 sc231ai_link_frequencies[] = { 378000000 };

struct sc231ai {
	struct v4l2_subdev sd;
	struct media_pad pad;
	struct v4l2_ctrl_handler controls;
	struct v4l2_ctrl *exposure_cluster[3];
	struct v4l2_ctrl *hflip, *vflip;
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

static void sc231ai_format(struct v4l2_mbus_framefmt *fmt)
{
	*fmt = (struct v4l2_mbus_framefmt) {
		.width = SC231AI_WIDTH, .height = SC231AI_HEIGHT,
		.code = SC231AI_CODE, .field = V4L2_FIELD_NONE,
		.colorspace = V4L2_COLORSPACE_RAW,
		.quantization = V4L2_QUANTIZATION_FULL_RANGE,
		.xfer_func = V4L2_XFER_FUNC_NONE,
	};
}

static int sc231ai_init_state(struct v4l2_subdev *sd,
			      struct v4l2_subdev_state *state)
{
	sc231ai_format(v4l2_subdev_state_get_format(state, 0));
	return 0;
}

static int sc231ai_set_format(struct v4l2_subdev *sd,
			      struct v4l2_subdev_state *state,
			      struct v4l2_subdev_format *fmt)
{
	struct sc231ai *sensor = to_sc231ai(sd);

	if (fmt->pad)
		return -EINVAL;
	if (fmt->which == V4L2_SUBDEV_FORMAT_ACTIVE && sensor->streaming)
		return -EBUSY;
	sc231ai_format(&fmt->format);
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
	if (size->pad || size->index || size->code != SC231AI_CODE)
		return -EINVAL;
	size->min_width = size->max_width = SC231AI_WIDTH;
	size->min_height = size->max_height = SC231AI_HEIGHT;
	return 0;
}

static int sc231ai_get_interval(struct v4l2_subdev *sd,
			       struct v4l2_subdev_state *state,
			       struct v4l2_subdev_frame_interval *interval)
{
	if (interval->pad || interval->stream)
		return -EINVAL;
	interval->interval = (struct v4l2_fract) { 1, 60 };
	return 0;
}

static int sc231ai_enum_interval(struct v4l2_subdev *sd,
				struct v4l2_subdev_state *state,
				struct v4l2_subdev_frame_interval_enum *interval)
{
	if (interval->pad || interval->stream || interval->index ||
	    interval->code != SC231AI_CODE ||
	    interval->width != SC231AI_WIDTH || interval->height != SC231AI_HEIGHT)
		return -EINVAL;
	interval->interval = (struct v4l2_fract) { 1, 60 };
	return 0;
}

static const struct v4l2_subdev_pad_ops sc231ai_pad_ops = {
	.enum_mbus_code = sc231ai_enum_code,
	.enum_frame_size = sc231ai_enum_size,
	.enum_frame_interval = sc231ai_enum_interval,
	.get_frame_interval = sc231ai_get_interval,
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

static int sc231ai_probe(struct i2c_client *client)
{
	struct device *dev = &client->dev;
	struct sc231ai *sensor;
	struct v4l2_ctrl *ctrl;
	int ret, hi, lo;

	if (!i2c_check_functionality(client->adapter, I2C_FUNC_I2C))
		return -EOPNOTSUPP;
	ret = sc231ai_endpoint(dev);
	if (ret)
		return dev_err_probe(dev, ret, "requires 2 lanes at 378 MHz\n");
	sensor = devm_kzalloc(dev, sizeof(*sensor), GFP_KERNEL);
	if (!sensor)
		return -ENOMEM;
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
	ctrl = v4l2_ctrl_new_std(&sensor->controls, NULL, V4L2_CID_HBLANK,
			       SC231AI_HTS - SC231AI_WIDTH, SC231AI_HTS - SC231AI_WIDTH,
			       1, SC231AI_HTS - SC231AI_WIDTH);
	if (ctrl)
		ctrl->flags |= V4L2_CTRL_FLAG_READ_ONLY;
	ctrl = v4l2_ctrl_new_std(&sensor->controls, NULL, V4L2_CID_VBLANK,
			       SC231AI_VTS - SC231AI_HEIGHT, SC231AI_VTS - SC231AI_HEIGHT,
			       1, SC231AI_VTS - SC231AI_HEIGHT);
	if (ctrl)
		ctrl->flags |= V4L2_CTRL_FLAG_READ_ONLY;
	sensor->exposure_cluster[0] = v4l2_ctrl_new_std(&sensor->controls,
		&sc231ai_control_ops, V4L2_CID_EXPOSURE,
		1, SC231AI_VTS - 11, 1, SC231AI_VTS - 11);
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
MODULE_DESCRIPTION("SmartSens SC231AI RAW10 sensor");
MODULE_LICENSE("GPL");
