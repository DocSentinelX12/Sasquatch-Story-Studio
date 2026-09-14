#pragma once

#include <cstdint>
#include <tiffio.h>

/*
 * OpenToonz currently uses libtiff's pre-4.3 typedef spellings in
 * tiio_tif.cpp. Modern libtiff documents those spellings as deprecated and
 * current Linux headers used by the CI worker no longer expose them.
 * Translate only the legacy source spellings to their C99 equivalents.
 */
#define uint32 uint32_t
#define uint16 uint16_t

/* Current libtiff documentation defines this public API with these types.
 * The declaration keeps older OpenToonz code buildable when the installed
 * header hides the declaration through its deprecation configuration.
 */
extern "C" uint32_t TIFFDefaultStripSize(TIFF *tif, uint32_t estimate);
