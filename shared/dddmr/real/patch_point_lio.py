"""Apply narrow, repeatable fixes to the pinned Point-LIO source."""
import sys
from pathlib import Path


def patch(root):
    path = Path(root) / "src/laserMapping.cpp"
    text = path.read_text()
    replacements = [
        ("crossmat_list.reserve(feats_down_size);", "crossmat_list.resize(feats_down_size);"),
        ("pbody_list.reserve(feats_down_size);", "pbody_list.resize(feats_down_size);"),
        ("cub_needrm.shrink_to_fit();", "cub_needrm.clear();"),
        ("meas.imu.shrink_to_fit();", "meas.imu.clear();"),
        ("last_timestamp_lidar = msg->header.stamp.sec;",
         "last_timestamp_lidar = get_time_sec(msg->header.stamp);"),
        ("    readParameters(nh);", """    readParameters(nh);
    // The sliding window needs an interior outside both move thresholds.
    if (cube_len <= 2.0 * MOV_THRESHOLD * DET_RANGE) {
        RCLCPP_FATAL(logger, "cube_side_length must exceed 3 * mapping.det_range");
        rclcpp::shutdown();
        return 2;
    }"""),
    ]
    for old, new in replacements:
        if old in new and new in text:
            continue
        if old in text:
            text = text.replace(old, new)
        elif new not in text:
            raise RuntimeError(f"Pinned source no longer matches: {old}")
    path.write_text(text)


if __name__ == "__main__":
    patch(sys.argv[1])
