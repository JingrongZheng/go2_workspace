import collections
import json
import sys
import numpy as np
import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

reader = rosbag2_py.SequentialReader()
reader.open(rosbag2_py.StorageOptions(uri=sys.argv[1], storage_id='sqlite3'),
            rosbag2_py.ConverterOptions('', ''))
types = {t.name: get_message(t.type) for t in reader.get_all_topics_and_types()}
stamps = collections.defaultdict(list)
frames = collections.defaultdict(set)
rings = set()
ranges = []
cloud_sizes = []
layout = {}
accel = []
gyro = []
state = {}
last_in_order = 0
while reader.has_next():
    topic, raw, arrived = reader.read_next()
    msg = deserialize_message(raw, types[topic])
    if not hasattr(msg, 'header'):
        state = {k: getattr(msg, k) for k in ('firmware_version','software_version','sdk_version',
                 'cloud_scan_num','cloud_frequency','imu_frequency','error_state','cloud_packet_loss_rate','imu_packet_loss_rate')}
        continue
    stamp = msg.header.stamp
    stamps[topic].append(stamp.sec + stamp.nanosec / 1e9)
    frames[topic].add(msg.header.frame_id)
    if topic.endswith('/imu'):
        a, g = msg.linear_acceleration, msg.angular_velocity
        accel.append([a.x,a.y,a.z])
        gyro.append([g.x,g.y,g.z])
    else:
        layout = {f.name: [f.offset,f.datatype,f.count] for f in msg.fields}
        endian = '>' if msg.is_bigendian else '<'
        times = np.ndarray((msg.width,), endian+'f4', buffer=msg.data,
                           offset=layout['time'][0], strides=(msg.point_step,))
        ring = np.ndarray((msg.width,), endian+'u2', buffer=msg.data,
                          offset=layout['ring'][0], strides=(msg.point_step,))
        ranges.append([float(min(times)),float(max(times)),float(times[-1])])
        last_in_order += int(times[-1] == max(times))
        rings.update(map(int, ring))
        cloud_sizes.append(msg.width)
report = {'topics': {}, 'cloud': {'fields_offset_type_count':layout, 'rings':sorted(rings),
          'points_min_median_max':[min(cloud_sizes),float(np.median(cloud_sizes)),max(cloud_sizes)],
          'point_time_min_s':min(x[0] for x in ranges), 'point_time_max_s':max(x[1] for x in ranges),
          'median_point_time_max_s':float(np.median([x[1] for x in ranges])),
          'last_point_is_latest_frames':last_in_order},
          'imu':{'median_accel':np.median(accel,axis=0).tolist(),'median_gyro':np.median(gyro,axis=0).tolist(),
                 'median_acceleration_norm':float(np.median(np.linalg.norm(accel,axis=1)))}, 'lidar_state':state}
for topic, seq in stamps.items():
    diff = np.diff(seq)
    report['topics'][topic] = {'frames': sorted(frames[topic]), 'messages':len(seq),
       'rate_hz':(len(seq)-1)/(seq[-1]-seq[0]),'median_period_s':float(np.median(diff)),
       'nonincreasing_stamps':int(np.count_nonzero(diff <= 0)), 'first_stamp':seq[0], 'last_stamp':seq[-1]}
im = np.sort(stamps['/utlidar/imu'])
cl = np.array(stamps['/utlidar/cloud'])
covered = (cl >= im[0]) & (cl <= im[-1])
report['imu']['cloud_headers_within_imu_time_range'] = int(sum(covered))
print(json.dumps(report,indent=2))
