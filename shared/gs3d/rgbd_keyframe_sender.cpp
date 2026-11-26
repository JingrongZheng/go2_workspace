// Capture color-aligned raw Z16 depth + high-quality RGB keyframes + factory intrinsics
// from RealSense D435i on the Go2 dock without ROS or Python dependencies.
//
// Binary protocol on stdout:
//   8 bytes  magic: "GO2GS001"
//   4 bytes  uint32 LE: header JSON byte length
//   N bytes  UTF-8 JSON: width, height, fps, target_hz, depth_scale, fx, fy, cx, cy, model, coeffs
// Then repeated frames:
//   4 bytes  magic: "KF01"
//   4 bytes  uint32 LE: sequence
//   8 bytes  int64  LE: dock wall clock ns (CLOCK_REALTIME)
//   8 bytes  double LE: RealSense hardware/sensor timestamp (ms)
//   4 bytes  uint32 LE: rgb_jpeg_bytes
//   4 bytes  uint32 LE: depth_zlib_bytes (zlib-compressed raw uint16_t width*height aligned to color)
//   rgb_jpeg_bytes + depth_zlib_bytes payload

#include <librealsense2/rs.hpp>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <jpeglib.h>
#include <zlib.h>

volatile std::sig_atomic_t running = 1;
void stop_capture(int) { running = 0; }

template <typename T>
void put_le(T value) {
    unsigned char buf[sizeof(T)];
    std::memcpy(buf, &value, sizeof(T));
    if (std::fwrite(buf, 1, sizeof(T), stdout) != sizeof(T)) {
        throw std::runtime_error("Output closed");
    }
}

std::vector<unsigned char> encode_jpeg(const rs2::video_frame& frame, int quality) {
    const auto* data = static_cast<const unsigned char*>(frame.get_data());
    jpeg_compress_struct encoder{};
    jpeg_error_mgr errors;
    encoder.err = jpeg_std_error(&errors);
    jpeg_create_compress(&encoder);
    unsigned char* encoded = nullptr;
    unsigned long size = 0;
    jpeg_mem_dest(&encoder, &encoded, &size);
    encoder.image_width = frame.get_width();
    encoder.image_height = frame.get_height();
    encoder.input_components = 3;
    encoder.in_color_space = JCS_RGB;
    jpeg_set_defaults(&encoder);
    jpeg_set_quality(&encoder, quality, TRUE);
    jpeg_start_compress(&encoder, TRUE);
    while (encoder.next_scanline < encoder.image_height) {
        auto row = const_cast<JSAMPLE*>(data + encoder.next_scanline * frame.get_stride_in_bytes());
        jpeg_write_scanlines(&encoder, &row, 1);
    }
    jpeg_finish_compress(&encoder);
    std::vector<unsigned char> result(encoded, encoded + size);
    std::free(encoded);
    jpeg_destroy_compress(&encoder);
    return result;
}

std::vector<unsigned char> compress_depth_z16(const rs2::depth_frame& depth) {
    const int width = depth.get_width();
    const int height = depth.get_height();
    const int stride = depth.get_stride_in_bytes();
    const size_t row_bytes = static_cast<size_t>(width) * sizeof(uint16_t);
    const size_t raw_size = row_bytes * static_cast<size_t>(height);

    std::vector<unsigned char> contiguous;
    const unsigned char* src = static_cast<const unsigned char*>(depth.get_data());
    if (stride != static_cast<int>(row_bytes)) {
        contiguous.resize(raw_size);
        for (int y = 0; y < height; ++y) {
            std::memcpy(contiguous.data() + y * row_bytes, src + y * stride, row_bytes);
        }
        src = contiguous.data();
    }

    uLongf bound = compressBound(raw_size);
    std::vector<unsigned char> out(bound);
    if (compress2(out.data(), &bound, src, raw_size, 1) != Z_OK) {
        throw std::runtime_error("zlib depth compression failed");
    }
    out.resize(bound);
    return out;
}

int64_t wall_clock_ns() {
    using namespace std::chrono;
    return duration_cast<nanoseconds>(system_clock::now().time_since_epoch()).count();
}

int main(int argc, char** argv) {
    std::signal(SIGTERM, stop_capture);
    std::signal(SIGINT, stop_capture);
    std::signal(SIGPIPE, SIG_IGN);

    int width = 848;
    int height = 480;
    int fps = 15;
    double target_hz = 2.5;
    int jpeg_quality = 95;
    int warmup_frames = 15;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--width" && i + 1 < argc) width = std::atoi(argv[++i]);
        else if (arg == "--height" && i + 1 < argc) height = std::atoi(argv[++i]);
        else if (arg == "--fps" && i + 1 < argc) fps = std::atoi(argv[++i]);
        else if (arg == "--target-hz" && i + 1 < argc) target_hz = std::atof(argv[++i]);
        else if (arg == "--jpeg-quality" && i + 1 < argc) jpeg_quality = std::atoi(argv[++i]);
        else if (arg == "--warmup" && i + 1 < argc) warmup_frames = std::atoi(argv[++i]);
    }
    if (target_hz <= 0.0) target_hz = 2.5;
    const double min_period_s = 1.0 / target_hz;

    try {
        rs2::pipeline pipe;
        rs2::config config;
        config.enable_stream(RS2_STREAM_DEPTH, width, height, RS2_FORMAT_Z16, fps);
        config.enable_stream(RS2_STREAM_COLOR, width, height, RS2_FORMAT_RGB8, fps);
        rs2::pipeline_profile profile = pipe.start(config);

        auto depth_sensor = profile.get_device().first<rs2::depth_sensor>();
        const float depth_scale = depth_sensor.get_depth_scale();
        auto color_vsp = profile.get_stream(RS2_STREAM_COLOR).as<rs2::video_stream_profile>();
        rs2_intrinsics intr = color_vsp.get_intrinsics();

        rs2::align align_to_color(RS2_STREAM_COLOR);

        // Warm up auto-exposure and white balance before emitting keyframes.
        for (int w = 0; w < warmup_frames && running; ++w) {
            rs2::frameset fs;
            pipe.try_wait_for_frames(&fs, 1000);
        }

        std::ostringstream hdr;
        hdr.precision(10);
        hdr << "{"
            << "\"width\":" << intr.width << ","
            << "\"height\":" << intr.height << ","
            << "\"fps\":" << fps << ","
            << "\"target_hz\":" << target_hz << ","
            << "\"depth_scale\":" << depth_scale << ","
            << "\"fx\":" << intr.fx << ","
            << "\"fy\":" << intr.fy << ","
            << "\"cx\":" << intr.ppx << ","
            << "\"cy\":" << intr.ppy << ","
            << "\"distortion_model\":\"" << rs2_distortion_to_string(intr.model) << "\","
            << "\"coeffs\":["
            << intr.coeffs[0] << "," << intr.coeffs[1] << "," << intr.coeffs[2] << ","
            << intr.coeffs[3] << "," << intr.coeffs[4] << "],"
            << "\"aligned_to\":\"color\""
            << "}";
        const std::string hdr_str = hdr.str();

        std::cerr << "D435i aligned RGB-D keyframe sender ready: "
                  << intr.width << "x" << intr.height << "@" << fps
                  << " -> " << target_hz << " Hz, depth_scale=" << depth_scale << "\n";

        std::fwrite("GO2GS001", 1, 8, stdout);
        put_le<uint32_t>(static_cast<uint32_t>(hdr_str.size()));
        if (std::fwrite(hdr_str.data(), 1, hdr_str.size(), stdout) != hdr_str.size()) {
            throw std::runtime_error("Output closed");
        }
        std::fflush(stdout);

        uint32_t sequence = 0;
        auto last_emit = std::chrono::steady_clock::now() - std::chrono::seconds(10);

        while (running) {
            rs2::frameset frames;
            if (!pipe.try_wait_for_frames(&frames, 1000)) continue;
            auto now = std::chrono::steady_clock::now();
            double dt = std::chrono::duration<double>(now - last_emit).count();
            if (dt < min_period_s) continue;

            rs2::frameset aligned = align_to_color.process(frames);
            auto rgb = aligned.get_color_frame();
            auto depth = aligned.get_depth_frame();
            if (!rgb || !depth) continue;

            int64_t dock_ns = wall_clock_ns();
            double sensor_ts_ms = rgb.get_timestamp();
            auto rgb_jpeg = encode_jpeg(rgb, jpeg_quality);
            auto depth_zlib = compress_depth_z16(depth);

            std::fwrite("KF01", 1, 4, stdout);
            put_le<uint32_t>(sequence++);
            put_le<int64_t>(dock_ns);
            put_le<double>(sensor_ts_ms);
            put_le<uint32_t>(static_cast<uint32_t>(rgb_jpeg.size()));
            put_le<uint32_t>(static_cast<uint32_t>(depth_zlib.size()));
            if (std::fwrite(rgb_jpeg.data(), 1, rgb_jpeg.size(), stdout) != rgb_jpeg.size()) {
                throw std::runtime_error("Output closed");
            }
            if (std::fwrite(depth_zlib.data(), 1, depth_zlib.size(), stdout) != depth_zlib.size()) {
                throw std::runtime_error("Output closed");
            }
            if (std::fflush(stdout)) {
                throw std::runtime_error("Output closed");
            }
            last_emit = now;
        }
        pipe.stop();
    } catch (const std::exception& error) {
        std::cerr << "D435i keyframe sender error: " << error.what() << "\n";
        return 1;
    }
    return 0;
}
