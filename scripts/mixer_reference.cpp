// Dumps the engine's FilamentMixer polynomial model, and what it computes for a fixed set of inputs, as JSON.
// Built and run by scripts/mixer-reference.sh against vendor/orcaslicer/src/libslic3r/FilamentMixerModel.hpp (MIT,
// Copyright (c) 2026 Justin Hayes), so the Python port in api/app/colour_mixer.py is checked against the real header.
//
// Usage: mixer_reference model|reference
#include <cstdio>
#include <cstring>
#include <random>
#include <string>
#include <vector>

#include "FilamentMixerModel.hpp"

namespace fm = filament_mixer;

static std::string hex_of(unsigned char r, unsigned char g, unsigned char b)
{
    char buf[8];
    std::snprintf(buf, sizeof(buf), "#%02X%02X%02X", r, g, b);
    return buf;
}

// The pairwise accumulation of Slic3r::blend_color_multi (FilamentMixer.cpp), without its measured-recipe lookup.
static std::string blend_multi(const std::vector<std::string>& hexes, const std::vector<int>& weights)
{
    unsigned char r = 128, g = 128, b = 128;
    int accumulated = 0;
    for (size_t i = 0; i < hexes.size(); ++i) {
        if (weights[i] <= 0)
            continue;
        unsigned rv = 0, gv = 0, bv = 0;
        std::sscanf(hexes[i].c_str(), "#%02x%02x%02x", &rv, &gv, &bv);
        if (accumulated == 0) {
            r = rv; g = gv; b = bv;
            accumulated = weights[i];
        } else {
            const int total = accumulated + weights[i];
            const float t = static_cast<float>(weights[i]) / static_cast<float>(total);
            fm::lerp(r, g, b, rv, gv, bv, t, &r, &g, &b);
            accumulated = total;
        }
    }
    return accumulated == 0 ? "#000000" : hex_of(r, g, b);
}

static void dump_model()
{
    std::printf("{\n  \"powers\": [");
    for (int i = 0; i < fm::detail::N_FEATURES; ++i) {
        std::printf("%s[", i ? "," : "");
        for (int j = 0; j < fm::detail::N_INPUTS; ++j)
            std::printf("%s%d", j ? "," : "", fm::detail::POWERS[i][j]);
        std::printf("]");
    }
    std::printf("],\n  \"coef\": [");
    for (int i = 0; i < fm::detail::N_FEATURES; ++i)
        std::printf("%s[%.17g,%.17g,%.17g]", i ? "," : "", fm::detail::COEF[i][0], fm::detail::COEF[i][1], fm::detail::COEF[i][2]);
    std::printf("],\n  \"intercept\": [%.17g,%.17g,%.17g]\n}\n", fm::detail::INTERCEPT[0], fm::detail::INTERCEPT[1],
                fm::detail::INTERCEPT[2]);
}

static void dump_reference()
{
    std::mt19937 rng(20260508);
    auto channel = [&] { return static_cast<int>(rng() % 256); };
    const float ts[] = {0.0f, 0.05f, 0.1f, 0.25f, 1.0f / 3.0f, 0.5f, 0.6f, 0.75f, 0.9f, 0.99f, 1.0f, -0.5f, 1.5f};

    std::printf("{\n  \"lerp\": [");
    bool first = true;
    auto emit_lerp = [&](int r1, int g1, int b1, int r2, int g2, int b2, float t) {
        unsigned char r, g, b;
        fm::lerp(r1, g1, b1, r2, g2, b2, t, &r, &g, &b);
        std::printf("%s\n    [%d,%d,%d,%d,%d,%d,%.9g,%d,%d,%d]", first ? "" : ",", r1, g1, b1, r2, g2, b2, t, r, g, b);
        first = false;
    };
    // The header's own example, the corners of the cube, then random pairs.
    emit_lerp(0, 33, 133, 252, 211, 0, 0.5f);
    const int corners[][3] = {{0, 0, 0}, {255, 255, 255}, {255, 0, 0}, {0, 255, 0}, {0, 0, 255}, {255, 255, 0}};
    for (const auto& a : corners)
        for (const auto& b : corners)
            emit_lerp(a[0], a[1], a[2], b[0], b[1], b[2], 0.5f);
    for (int i = 0; i < 300; ++i)
        emit_lerp(channel(), channel(), channel(), channel(), channel(), channel(), ts[i % (sizeof(ts) / sizeof(ts[0]))]);
    std::printf("\n  ],\n  \"multi\": [");

    first = true;
    auto emit_multi = [&](const std::vector<std::string>& hexes, const std::vector<int>& weights) {
        std::printf("%s\n    {\"colours\": [", first ? "" : ",");
        for (size_t i = 0; i < hexes.size(); ++i)
            std::printf("%s\"%s\"", i ? "," : "", hexes[i].c_str());
        std::printf("], \"weights\": [");
        for (size_t i = 0; i < weights.size(); ++i)
            std::printf("%s%d", i ? "," : "", weights[i]);
        std::printf("], \"result\": \"%s\"}", blend_multi(hexes, weights).c_str());
        first = false;
    };
    const int weight_sets[][3] = {{50, 50, 0}, {75, 25, 0}, {80, 20, 0}, {90, 10, 0}, {1, 1, 0},
                                  {50, 25, 25}, {34, 33, 33}, {60, 30, 10}, {20, 20, 60}, {0, 50, 50}};
    for (int i = 0; i < 150; ++i) {
        const bool three = i % 3 == 0;
        std::vector<std::string> hexes;
        for (int c = 0; c < (three ? 3 : 2); ++c)
            hexes.push_back(hex_of(channel(), channel(), channel()));
        const int* w = weight_sets[i % (sizeof(weight_sets) / sizeof(weight_sets[0]))];
        emit_multi(hexes, std::vector<int>(w, w + hexes.size()));
    }
    std::printf("\n  ]\n}\n");
}

int main(int argc, char** argv)
{
    if (argc == 2 && !std::strcmp(argv[1], "model"))
        dump_model();
    else if (argc == 2 && !std::strcmp(argv[1], "reference"))
        dump_reference();
    else
        return 2;
    return 0;
}
