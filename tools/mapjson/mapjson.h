// mapjson.h

#ifndef MAPJSON_H
#define MAPJSON_H

#include <cstdio>
using std::fprintf; using std::exit;

#include <cstdlib>

#include <string>

enum class MapBuildMode
{
    Emerald,
    FireRed,
    Ruby,
    AllRegions,
};

enum class DataDialect
{
    Emerald,
    FireRed,
    Ruby,
};

struct MapBuildPolicy
{
    MapBuildMode mode;
    DataDialect defaultDialect;

    bool IncludesRegion(const std::string &region) const;
    bool IncludesLayout(const std::string &layoutFormat) const;
    bool IsProduct() const { return mode == MapBuildMode::AllRegions; }
};

MapBuildPolicy ParseBuildPolicy(const std::string &value);
const char *MapBuildModeName(MapBuildMode mode);
const char *DataDialectName(DataDialect dialect);

#ifdef _MSC_VER

#define FATAL_ERROR(format, ...)          \
do                                        \
{                                         \
    fprintf(stderr, format, __VA_ARGS__); \
    exit(1);                              \
} while (0)

#else

#define FATAL_ERROR(format, ...)            \
do                                          \
{                                           \
    fprintf(stderr, format, ##__VA_ARGS__); \
    exit(1);                                \
} while (0)

#endif // _MSC_VER

#endif // MAPJSON_H
