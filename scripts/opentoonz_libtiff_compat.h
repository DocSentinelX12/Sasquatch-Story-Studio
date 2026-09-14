#pragma once

#include <cstdint>

/*
 * OpenToonz bundles libtiff 4.0.3 headers that use libtiff's legacy
 * fixed-width typedef spellings. On the current Ubuntu/GCC toolchain those
 * spellings are not provided by the bundled header's generated configuration
 * path, so the header fails before the aliases can be introduced later.
 * Define the compatibility names only while tiffio.h is being parsed.
 */
#define int8 int8_t
#define uint8 uint8_t
#define int16 int16_t
#define uint16 uint16_t
#define int32 int32_t
#define uint32 uint32_t
#define int64 int64_t
#define uint64 uint64_t

#include <tiffio.h>

#undef int8
#undef uint8
#undef int16
#undef uint16
#undef int32
#undef uint32
#undef int64
#undef uint64
