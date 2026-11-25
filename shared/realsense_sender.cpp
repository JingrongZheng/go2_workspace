// Capture RGB and colorized depth without ROS or Python bindings.
#include <librealsense2/rs.hpp>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <jpeglib.h>

volatile std::sig_atomic_t running = 1;
void stop_capture(int) { running = 0; }
void put32(uint32_t value) {
    unsigned char b[4];
    for (int i = 0; i < 4; ++i) b[i] = (value >> (8 * i)) & 255;
    if (std::fwrite(b, 1, 4, stdout) != 4) throw std::runtime_error("Output closed");
}
std::vector<unsigned char> encode_image(const rs2::video_frame& frame) {
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
    jpeg_set_quality(&encoder, 75, TRUE);
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
int main() {
    std::signal(SIGTERM, stop_capture);
    std::signal(SIGINT, stop_capture);
    std::signal(SIGPIPE, SIG_IGN);
    try {
        constexpr int width = 640, height = 360, fps = 15;
        rs2::pipeline pipe;
        rs2::config config;
        config.enable_stream(RS2_STREAM_DEPTH, width, height, RS2_FORMAT_Z16, fps);
        config.enable_stream(RS2_STREAM_COLOR, width, height, RS2_FORMAT_RGB8, fps);
        rs2::colorizer colors;
        colors.set_option(RS2_OPTION_HISTOGRAM_EQUALIZATION_ENABLED, 0.f);
        colors.set_option(RS2_OPTION_MIN_DISTANCE, 0.2f);
        colors.set_option(RS2_OPTION_MAX_DISTANCE, 5.f);
        pipe.start(config);
        std::cerr << "D435i RGB/depth: 640x360@15; depth visualization 0.2-5m\n";
        std::fwrite("GO2RGBD2", 1, 8, stdout);
        put32(width); put32(height); put32(fps);
        std::fflush(stdout);
        uint32_t sequence = 0;
        while (running) {
            rs2::frameset frames;
            if (!pipe.try_wait_for_frames(&frames, 1000)) continue;
            auto rgb = frames.get_color_frame();
            auto depth = frames.get_depth_frame();
            if (!rgb || !depth) continue;
            auto visual = colors.colorize(depth);
            if (rgb.get_width() != width || rgb.get_height() != height ||
                visual.get_width() != width || visual.get_height() != height ||
                rgb.get_bytes_per_pixel() != 3 || visual.get_bytes_per_pixel() != 3)
                throw std::runtime_error("Unexpected camera frame format");
            std::fwrite("FRM1", 1, 4, stdout);
            put32(sequence++);
            auto rgb_jpeg = encode_image(rgb);
            auto depth_jpeg = encode_image(visual);
            put32(rgb_jpeg.size()); put32(depth_jpeg.size());
            for (const auto* image : {&rgb_jpeg, &depth_jpeg})
                if (std::fwrite(image->data(), 1, image->size(), stdout) != image->size())
                    throw std::runtime_error("Output closed");
            if (std::fflush(stdout)) throw std::runtime_error("Output closed");
        }
        pipe.stop();
    } catch (const std::exception& error) {
        std::cerr << "D435i sender: " << error.what() << '\n';
        return 1;
    }
}
