// mapjson.cpp

#include <iostream>
using std::cout; using std::endl;

#include <string>
using std::string;

#include <vector>
using std::vector;

#include <algorithm>
using std::sort; using std::find;

#include <map>
using std::map;

#include <set>
using std::set;

#include <fstream>
using std::ofstream; using std::ifstream;

#include <sstream>
using std::ostringstream;

#include <limits>
using std::numeric_limits;

#include "json11.h"
using json11::Json;

#include <regex>

#include "mapjson.h"

#include <filesystem>
#include <system_error>
#include <chrono>
#include <cctype>
#include <cstdint>
#include <cmath>

#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#include <thread>
#else
#include <fcntl.h>
#include <sys/file.h>
#include <unistd.h>
#endif

// System directory separator
string sep;

const char *MapBuildModeName(MapBuildMode mode)
{
    switch (mode) {
    case MapBuildMode::Emerald: return "emerald";
    case MapBuildMode::FireRed: return "firered";
    case MapBuildMode::Ruby: return "ruby";
    case MapBuildMode::AllRegions: return "allregions";
    }
    return "unknown";
}

const char *DataDialectName(DataDialect dialect)
{
    switch (dialect) {
    case DataDialect::Emerald: return "emerald";
    case DataDialect::FireRed: return "firered";
    case DataDialect::Ruby: return "ruby";
    }
    return "unknown";
}

static string DefaultRegionName(DataDialect dialect)
{
    return dialect == DataDialect::FireRed ? "REGION_KANTO" : "REGION_HOENN";
}

static string DefaultLayoutName(DataDialect dialect)
{
    switch (dialect) {
    case DataDialect::Emerald: return "emerald";
    case DataDialect::FireRed: return "frlg";
    case DataDialect::Ruby: return "ruby";
    }
    return "";
}

struct LayoutFormatSpec
{
    const char *constant;
    int encodedValue;
};

static LayoutFormatSpec GetLayoutFormatSpec(const string &value)
{
    if (value == "emerald") return {"MAP_LAYOUT_FORMAT_EMERALD", 0};
    if (value == "frlg") return {"MAP_LAYOUT_FORMAT_FRLG", 1};
    if (value == "johto") return {"MAP_LAYOUT_FORMAT_JOHTO", 2};
    FATAL_ERROR("unknown layout format '%s'\n", value.c_str());
}

MapBuildPolicy ParseBuildPolicy(const string &value)
{
    if (value == "emerald")
        return {MapBuildMode::Emerald, DataDialect::Emerald};
    if (value == "firered")
        return {MapBuildMode::FireRed, DataDialect::FireRed};
    if (value == "ruby")
        return {MapBuildMode::Ruby, DataDialect::Ruby};
    if (value == "allregions")
        return {MapBuildMode::AllRegions, DataDialect::Emerald};
    FATAL_ERROR("ERROR: unknown map build mode '%s'.\n", value.c_str());
}

bool MapBuildPolicy::IncludesRegion(const string &region) const
{
    if (mode == MapBuildMode::AllRegions)
        return region == "REGION_HOENN" || region == "REGION_KANTO" || region == "REGION_JOHTO";
    return region == DefaultRegionName(defaultDialect);
}

bool MapBuildPolicy::IncludesLayout(const string &layoutFormat) const
{
    if (mode == MapBuildMode::AllRegions)
        return layoutFormat == "emerald" || layoutFormat == "frlg" || layoutFormat == "johto";
    return layoutFormat == DefaultLayoutName(defaultDialect);
}

string read_text_file(string filepath) {
    ifstream in_file(filepath);

    if (!in_file.is_open())
        FATAL_ERROR("Cannot open file %s for reading.\n", filepath.c_str());

    string text;

    in_file.seekg(0, std::ios::end);
    text.resize(in_file.tellg());

    in_file.seekg(0, std::ios::beg);
    in_file.read(&text[0], text.size());

    in_file.close();

    return text;
}

void write_text_file(string filepath, string text) {
    ofstream out_file(filepath, std::ofstream::binary);

    if (!out_file.is_open())
        FATAL_ERROR("Cannot open file %s for writing.\n", filepath.c_str());

    out_file << text;

    out_file.close();
}


string json_to_string(const Json &data, const string &field = "", bool silent = false) {
    const Json value = !field.empty() ? data[field] : data;
    string output = "";
    switch (value.type()) {
        case Json::Type::STRING:
            output = value.string_value();
            break;
        case Json::Type::NUMBER:
            output = std::to_string(value.int_value());
            break;
        case Json::Type::BOOL:
            output = value.bool_value() ? "TRUE" : "FALSE";
            break;
        case Json::Type::NUL:
            output = "";
            break;
        default:{
            if (!silent) {
                string s = !field.empty() ? ("Value for '" + field + "'") : "JSON field";
                FATAL_ERROR("%s is unexpected type; expected string, number, or bool.\n", s.c_str());
            }
        }
    }

    if (!silent && output.empty()) {
        string s = !field.empty() ? ("Value for '" + field + "'") : "JSON field";
        FATAL_ERROR("%s cannot be empty.\n", s.c_str());
    }

    return output;
}

string get_generated_warning(const string &filename, bool isAsm) {
    ostringstream warning;
    if (isAsm) {
        warning << "@\n"
                << "@ DO NOT MODIFY THIS FILE! It is auto-generated from " << filename << "\n"
                << "@\n\n";
    } else {
        string safe_filename = filename;
        size_t pos = 0;
        while ((pos = safe_filename.find("*/", pos)) != string::npos) {
            safe_filename.replace(pos, 2, "* /");
            pos += 3;
        }
        warning << "/*\n"
                << " * DO NOT MODIFY THIS FILE! It is auto-generated from " << safe_filename << "\n"
                << " */\n\n";
    }
    return warning.str();
}

string get_include_guard_start(const string &name) {
    ostringstream guard;
    guard << "#ifndef GUARD_" << name << "_H\n"
          << "#define GUARD_" << name << "_H\n\n";
    return guard.str();
}

string get_include_guard_end(const string &name) {
    ostringstream guard;
    guard << "#endif /* GUARD_" << name << "_H */\n";
    return guard.str();
}

string generate_map_header_text(Json map_data, Json layouts_data, const MapBuildPolicy &policy,
                                size_t connection_count) {
    string map_layout_id = json_to_string(map_data, "layout");

    vector<Json> matched;

    for (auto &layout : layouts_data["layouts"].array_items()) {
        if (map_layout_id == json_to_string(layout, "id", true))
            matched.push_back(layout);
    }

    if (matched.size() != 1)
        FATAL_ERROR("Failed to find matching layout for %s.\n", map_layout_id.c_str());

    Json layout = matched[0];

    ostringstream text;

    string mapName = json_to_string(map_data, "name");
    text << get_generated_warning("data/maps/" + mapName + "/map.json", true);

    text << "\t.align 2\n" << mapName << ":\n"
         << "\t.4byte " << json_to_string(layout, "name") << "\n";

    if (map_data.object_items().find("shared_events_map") != map_data.object_items().end())
        text << "\t.4byte " << json_to_string(map_data, "shared_events_map") << "_MapEvents\n";
    else
        text << "\t.4byte " << mapName << "_MapEvents\n";

    if (map_data.object_items().find("shared_scripts_map") != map_data.object_items().end())
        text << "\t.4byte " << json_to_string(map_data, "shared_scripts_map") << "_MapScripts\n";
    else
        text << "\t.4byte " << mapName << "_MapScripts\n";

    if (connection_count > 0 && json_to_string(map_data, "connections_no_include", true) != "TRUE")
        text << "\t.4byte " << mapName << "_MapConnections\n";
    else
        text << "\t.4byte NULL\n";

    text << "\t.2byte " << json_to_string(map_data, "music") << "\n"
         << "\t.2byte " << json_to_string(layout, "id") << "\n"
         << "\t.2byte " << json_to_string(map_data, "region_map_section") << "\n"
         << "\t.byte "  << json_to_string(map_data, "requires_flash") << "\n"
         << "\t.byte "  << json_to_string(map_data, "weather") << "\n"
         << "\t.byte "  << json_to_string(map_data, "map_type") << "\n";

    string floor_number = json_to_string(map_data, "floor_number", true);
    if (floor_number.empty())
        text << "\t.byte 0\n";
    else
        text << "\t.byte " << floor_number << "\n";

    text << "\t.byte 0\n";

    if (policy.defaultDialect == DataDialect::Ruby)
        text << "\t.byte " << json_to_string(map_data, "show_map_name") << "\n";
    else
        text << "\tmap_header_flags "
             << "allow_cycling=" << json_to_string(map_data, "allow_cycling") << ", "
             << "allow_escaping=" << json_to_string(map_data, "allow_escaping") << ", "
             << "allow_running=" << json_to_string(map_data, "allow_running") << ", "
             << "show_map_name=" << json_to_string(map_data, "show_map_name") << "\n";

     text << "\t.byte " << json_to_string(map_data, "battle_scene") << "\n"
          << "\t.byte 0, 0, 0\n\n";

    return text.str();
}

static vector<Json> filtered_map_connections(Json map_data, const vector<string> &existing_maps) {
    vector<Json> connections;
    for (const Json &connection : map_data["connections"].array_items()) {
        if (find(existing_maps.begin(), existing_maps.end(), json_to_string(connection, "map")) != existing_maps.end())
            connections.push_back(connection);
    }
    return connections;
}

string generate_map_connections_text(Json map_data, const vector<Json> &connections) {
    if (map_data["connections"] == Json())
        return string("\n");

    string mapName = json_to_string(map_data, "name");

    ostringstream text;
    text << get_generated_warning("data/maps/" + mapName + "/map.json", true);
    text << mapName << "_MapConnectionsList:\n";

    for (const Json &connection : connections) {
        text << "\tconnection "
             << json_to_string(connection, "direction") << ", "
             << json_to_string(connection, "offset") << ", "
             << json_to_string(connection, "map") << "\n";
    }

    text << "\n" << mapName << "_MapConnections:\n"
         << "\t.4byte " << connections.size() << "\n"
         << "\t.4byte " << mapName << "_MapConnectionsList\n\n";

    return text.str();
}

string generate_map_events_text(Json map_data, const map<string, int> &hidden_item_flags) {
    if (map_data.object_items().find("shared_events_map") != map_data.object_items().end())
        return string("\n");

    string mapName = json_to_string(map_data, "name");

    ostringstream text;
    text << get_generated_warning("data/maps/" + mapName + "/map.json", true);
    text << "\t.align 2\n\n";

    string objects_label, warps_label, coords_label, bgs_label;

    if (map_data["object_events"].array_items().size() > 0) {
        objects_label = mapName + "_ObjectEvents";
        text << objects_label << ":\n";
        for (unsigned int i = 0; i < map_data["object_events"].array_items().size(); i++) {
            auto obj_event = map_data["object_events"].array_items()[i];
            string type = json_to_string(obj_event, "type", true);

            // If no type field is present, assume it's a regular object event.
            if (type == "" || type == "object") {
                text << "\tobject_event " << i + 1 << ", "
                     << json_to_string(obj_event, "graphics_id") << ", "
                     << json_to_string(obj_event, "x") << ", "
                     << json_to_string(obj_event, "y") << ", "
                     << json_to_string(obj_event, "elevation") << ", "
                     << json_to_string(obj_event, "movement_type") << ", "
                     << json_to_string(obj_event, "movement_range_x") << ", "
                     << json_to_string(obj_event, "movement_range_y") << ", "
                     << json_to_string(obj_event, "trainer_type") << ", "
                     << json_to_string(obj_event, "trainer_sight_or_berry_tree_id") << ", "
                     << json_to_string(obj_event, "script") << ", "
                     << json_to_string(obj_event, "flag") << "\n";
            } else if (type == "clone") {
                text << "\tclone_event " << i + 1 << ", "
                     << json_to_string(obj_event, "graphics_id") << ", "
                     << json_to_string(obj_event, "x") << ", "
                     << json_to_string(obj_event, "y") << ", "
                     << json_to_string(obj_event, "target_local_id") << ", "
                     << json_to_string(obj_event, "target_map") << "\n";
            } else {
                FATAL_ERROR("Unknown object event type '%s'. Expected 'object' or 'clone'.\n", type.c_str());
            }
        }
        text << "\n";
    } else {
        objects_label = "NULL";
    }

    if (map_data["warp_events"].array_items().size() > 0) {
        warps_label = mapName + "_MapWarps";
        text << warps_label << ":\n";
        for (auto &warp_event : map_data["warp_events"].array_items()) {
            text << "\twarp_def "
                 << json_to_string(warp_event, "x") << ", "
                 << json_to_string(warp_event, "y") << ", "
                 << json_to_string(warp_event, "elevation") << ", "
                 << json_to_string(warp_event, "dest_warp_id") << ", "
                 << json_to_string(warp_event, "dest_map") << "\n";
        }
        text << "\n";
    } else {
        warps_label = "NULL";
    }

    if (map_data["coord_events"].array_items().size() > 0) {
        coords_label = mapName + "_MapCoordEvents";
        text << coords_label << ":\n";
        for (auto &coord_event : map_data["coord_events"].array_items()) {
            string type = json_to_string(coord_event, "type");
            if (type == "trigger") {
                text << "\tcoord_event "
                     << json_to_string(coord_event, "x") << ", "
                     << json_to_string(coord_event, "y") << ", "
                     << json_to_string(coord_event, "elevation") << ", "
                     << json_to_string(coord_event, "var") << ", "
                     << json_to_string(coord_event, "var_value") << ", "
                     << json_to_string(coord_event, "script") << "\n";
            }
            else if (type == "weather") {
                text << "\tcoord_weather_event "
                     << json_to_string(coord_event, "x") << ", "
                     << json_to_string(coord_event, "y") << ", "
                     << json_to_string(coord_event, "elevation") << ", "
                     << json_to_string(coord_event, "weather") << "\n";
            } else {
                FATAL_ERROR("Unknown coord event type '%s'. Expected 'trigger' or 'weather'.\n", type.c_str());
            }
        }
        text << "\n";
    } else {
        coords_label = "NULL";
    }

    if (map_data["bg_events"].array_items().size() > 0) {
        bgs_label = mapName + "_MapBGEvents";
        text << bgs_label << ":\n";
        for (auto &bg_event : map_data["bg_events"].array_items()) {
            string type = json_to_string(bg_event, "type");
            if (type == "sign") {
                text << "\tbg_sign_event "
                     << json_to_string(bg_event, "x") << ", "
                     << json_to_string(bg_event, "y") << ", "
                     << json_to_string(bg_event, "elevation") << ", "
                     << json_to_string(bg_event, "player_facing_dir") << ", "
                     << json_to_string(bg_event, "script") << "\n";
            }
            else if (type == "hidden_item") {
                string quantity = json_to_string(bg_event, "quantity", true);
                if (quantity.empty()) {
                    quantity = "1";
                }
                string underfoot = json_to_string(bg_event, "underfoot", true);
                if (underfoot.empty()) {
                    underfoot = "FALSE";
                }
                const string reviewed_flag = json_to_string(bg_event, "flag");
                auto allocated_flag = hidden_item_flags.find(reviewed_flag);
                const string emitted_flag = allocated_flag == hidden_item_flags.end()
                    ? reviewed_flag : std::to_string(allocated_flag->second);
                text << "\tbg_hidden_item_event "
                     << json_to_string(bg_event, "x") << ", "
                     << json_to_string(bg_event, "y") << ", "
                     << json_to_string(bg_event, "elevation") << ", "
                     << json_to_string(bg_event, "item") << ", "
                     << emitted_flag << ", "
                     << quantity << ", "
                     << underfoot << "\n";
            }
            else if (type == "secret_base") {
                text << "\tbg_secret_base_event "
                     << json_to_string(bg_event, "x") << ", "
                     << json_to_string(bg_event, "y") << ", "
                     << json_to_string(bg_event, "elevation") << ", "
                     << json_to_string(bg_event, "secret_base_id") << "\n";
            } else {
                FATAL_ERROR("Unknown bg event type '%s'. Expected 'sign', 'hidden_item', or 'secret_base'.\n", type.c_str());
            }
        }
        text << "\n";
    } else {
        bgs_label = "NULL";
    }

    text << mapName << "_MapEvents::\n"
         << "\tmap_events " << objects_label << ", " << warps_label << ", "
         << coords_label << ", " << bgs_label << "\n\n";

    return text.str();
}

string strip_trailing_separator(string filename) {
    if(filename.back() == '/' || filename.back() == '\\')
        filename.pop_back();

    return filename;
}
void infer_separator(string filename) {
    size_t dir_pos = filename.find_last_of("/\\");
    sep = filename[dir_pos];
}
string file_parent(string filename){
    size_t dir_pos = filename.find_last_of("/\\");
    return filename.substr(0, dir_pos + 1);
}

void process_map(string map_filepath, string layouts_filepath, string output_dir,
                 const MapBuildPolicy &policy, const vector<string> &existing_maps,
                 const map<string, int> &hidden_item_flags = {}) {
    string mapdata_err, layouts_err;

    string mapdata_json_text = read_text_file(map_filepath);
    string layouts_json_text = read_text_file(layouts_filepath);

    Json map_data = Json::parse(mapdata_json_text, mapdata_err);
    if (map_data == Json())
        FATAL_ERROR("%s\n", mapdata_err.c_str());

    Json layouts_data = Json::parse(layouts_json_text, layouts_err);
    if (layouts_data == Json())
        FATAL_ERROR("%s\n", layouts_err.c_str());

    const vector<Json> connections = filtered_map_connections(map_data, existing_maps);
    string header_text = generate_map_header_text(map_data, layouts_data, policy, connections.size());
    string events_text = generate_map_events_text(map_data, hidden_item_flags);
    string connections_text = generate_map_connections_text(map_data, connections);

    string out_dir = strip_trailing_separator(output_dir).append(sep);
    write_text_file(out_dir + "header.inc", header_text);
    write_text_file(out_dir + "events.inc", events_text);
    write_text_file(out_dir + "connections.inc", connections_text);
}

void process_event_constants(const vector<string> &map_filepaths, string output_ids_file) {
    string warning = get_generated_warning("data/maps/<map>/map.json", false);

    string guard_name = "CONSTANTS_MAP_EVENT_IDS";
    ostringstream ids_file_text;
    ids_file_text << get_include_guard_start(guard_name) << warning;

    for (const string &filepath : map_filepaths) {
        string err;
        string map_json_text = read_text_file(filepath);
        Json map_data = Json::parse(map_json_text, err);
        if (map_data == Json())
            FATAL_ERROR("Failed to read '%s' while generating map event constants: %s\n", filepath.c_str(), err.c_str());

        string map_id = json_to_string(map_data, "id");

        // Get IDs from the object/clone events.
        ostringstream map_ids_text;
        auto obj_events = map_data["object_events"].array_items();
        for (unsigned int i = 0; i < obj_events.size(); i++) {
            auto obj_event = obj_events[i];
            if (obj_event.object_items().find("local_id") != obj_event.object_items().end())
                map_ids_text << "#define " << json_to_string(obj_event, "local_id") << " " << i + 1 << "\n";
        }
        // Get IDs from the warp events.
        auto warp_events = map_data["warp_events"].array_items();
        for (unsigned int i = 0; i < warp_events.size(); i++) {
            auto warp_event = warp_events[i];
            if (warp_event.object_items().find("warp_id") != warp_event.object_items().end())
                map_ids_text << "#define " << json_to_string(warp_event, "warp_id") << " " << i << "\n";
        }
        // Only output if we found any IDs
        string temp = map_ids_text.str();
        if (!temp.empty()) {
            ids_file_text << "/* " << map_id << " */\n" << temp << "\n";
        }
    }

    ids_file_text << get_include_guard_end(guard_name);
    write_text_file(output_ids_file, ids_file_text.str());
}

string generate_groups_text(Json groups_data, vector<string> &invalid_maps) {
    ostringstream text;

    text << get_generated_warning("data/maps/map_groups.json", true);

    vector<string> valid_groups;
    for (auto &key : groups_data["group_order"].array_items()) {
        string group = json_to_string(key);
        vector<string> valid_maps;
        auto maps = groups_data[group].array_items();
        for (Json &map_name : maps) {
            string map_name_str = json_to_string(map_name);
            auto it = find(invalid_maps.begin(), invalid_maps.end(), map_name_str);
            if (it == invalid_maps.end()) {
                valid_maps.push_back(map_name_str);
            }
        }

        const bool reviewed_empty_group = group == "gMapGroup_IndoorSSAqua"
            && maps.empty();
        if (valid_maps.size() > 0 || reviewed_empty_group) {
            text << group << "::\n";
            for (string map : valid_maps)
                text << "\t.4byte " << map << "\n";
            if (reviewed_empty_group)
                text << "\t.4byte " << group << "\n";
            text << "\n";
            valid_groups.push_back(group);
        }
    }

    text << "\t.align 2\n" << "gMapGroups::\n";
    for (auto &group : groups_data["group_order"].array_items()) {
        string group_str = json_to_string(group);
        if (find(valid_groups.begin(), valid_groups.end(), group_str) != valid_groups.end())
            text << "\t.4byte " << group_str << "\n";
        else
            text << "\t.4byte NULL\n";
    }
    text << "gMapGroupsEnd::\n\n";

    return text.str();
}

static bool ends_with(const string &value, const string &suffix)
{
    return value.size() >= suffix.size()
        && value.compare(value.size() - suffix.size(), suffix.size(), suffix) == 0;
}

static string humanize_debug_name_component(const string &identifier)
{
    string display;

    for (size_t i = 0; i < identifier.size(); i++) {
        const unsigned char current = identifier[i];
        const unsigned char previous = i == 0 ? 0 : identifier[i - 1];
        const unsigned char next = i + 1 == identifier.size() ? 0 : identifier[i + 1];
        const bool starts_word = i > 0
            && ((std::isupper(current) && std::islower(previous))
             || (std::isupper(current) && std::isupper(previous) && std::islower(next))
             || (std::isupper(current) && std::isdigit(previous))
             || (std::isdigit(current) && std::islower(previous)));

        if (starts_word)
            display += ' ';
        display += current;
    }

    return display;
}

static string humanize_debug_map_name(string identifier)
{
    constexpr size_t max_line_length = 32;

    if (ends_with(identifier, "_Frlg"))
        identifier.resize(identifier.size() - string("_Frlg").size());

    string display;
    size_t start = 0;
    while (start <= identifier.size()) {
        const size_t separator = identifier.find('_', start);
        const size_t end = separator == string::npos ? identifier.size() : separator;
        if (!display.empty())
            display += ' ';
        display += humanize_debug_name_component(identifier.substr(start, end - start));
        if (separator == string::npos)
            break;
        start = separator + 1;
    }

    if (display.size() <= max_line_length)
        return display;

    size_t best_separator = string::npos;
    size_t best_longest_line = string::npos;
    size_t separator = display.find(' ');
    while (separator != string::npos) {
        const size_t left_length = separator;
        const size_t right_length = display.size() - separator - 1;
        const size_t longest_line = std::max(left_length, right_length);
        if (left_length <= max_line_length
         && right_length <= max_line_length
         && longest_line < best_longest_line) {
            best_separator = separator;
            best_longest_line = longest_line;
        }
        separator = display.find(' ', separator + 1);
    }

    if (best_separator == string::npos)
        FATAL_ERROR("Debug map name '%s' cannot fit in two %zu-character lines\n", identifier.c_str(), max_line_length);

    display.replace(best_separator, 1, "\\n");
    return display;
}

static string humanize_debug_group_name(string identifier)
{
    const string prefix = "gMapGroup_";
    if (identifier.compare(0, prefix.size(), prefix) == 0)
        identifier.erase(0, prefix.size());
    if (ends_with(identifier, "_Frlg"))
        identifier.resize(identifier.size() - string("_Frlg").size());

    for (char &character : identifier) {
        if (character == '_')
            character = ' ';
    }
    return humanize_debug_name_component(identifier);
}

// This version is part of the named-warp map-registry/content contract. Bump it
// whenever the generator changes how an identity-covered value is interpreted.
static constexpr const char *DEBUG_NAMED_WARP_FORMAT = "named-warp-v1";

static void debug_identity_add(uint64_t &identity, const string &value)
{
    // Length framing makes the stream unambiguous without relying on a value
    // that JSON strings cannot contain.
    uint64_t length = value.size();
    for (int i = 0; i < 8; i++) {
        identity ^= static_cast<uint8_t>(length >> (i * 8));
        identity *= UINT64_C(1099511628211);
    }
    for (const unsigned char byte : value) {
        identity ^= byte;
        identity *= UINT64_C(1099511628211);
    }
}

static uint64_t generate_debug_named_warp_identity(const Json &groups_data,
                                                   const map<string, Json> &maps_by_name)
{
    string err;
    const Json sections_document = Json::parse(
        read_text_file("src/data/region_map/region_map_sections.json"), err);
    if (sections_document == Json())
        FATAL_ERROR("Failed to read region-map section metadata for debug identity: %s\n", err.c_str());

    map<string, string> section_presentations;
    for (const Json &section : sections_document["map_sections"].array_items())
        section_presentations[json_to_string(section, "id")] = json_to_string(section, "region_map_type");

    uint64_t identity = UINT64_C(14695981039346656037);
    debug_identity_add(identity, DEBUG_NAMED_WARP_FORMAT);
    for (const Json &group_value : groups_data["group_order"].array_items()) {
        const string group_name = json_to_string(group_value);
        debug_identity_add(identity, "group");
        debug_identity_add(identity, group_name);
        for (const Json &map_value : groups_data[group_name].array_items()) {
            const string registry_name = json_to_string(map_value);
            const auto map_it = maps_by_name.find(registry_name);
            if (map_it == maps_by_name.end())
                FATAL_ERROR("Map '%s' is absent while generating debug identity\n", registry_name.c_str());
            const Json &map_data = map_it->second;
            const string section_id = json_to_string(map_data, "region_map_section");
            const auto section_it = section_presentations.find(section_id);
            if (section_it == section_presentations.end())
                FATAL_ERROR("Map '%s' has unknown region-map section '%s'\n",
                            registry_name.c_str(), section_id.c_str());

            debug_identity_add(identity, "map");
            debug_identity_add(identity, registry_name);
            debug_identity_add(identity, json_to_string(map_data, "name"));
            debug_identity_add(identity, json_to_string(map_data, "id", true));
            string region = json_to_string(map_data, "region", true);
            if (region.empty())
                region = "<default>";
            debug_identity_add(identity, region);
            debug_identity_add(identity, json_to_string(map_data, "map_type"));
            debug_identity_add(identity, section_id);
            debug_identity_add(identity, section_it->second);

            const Json::array warps = map_data["warp_events"].array_items();
            debug_identity_add(identity, std::to_string(warps.size()));
            for (const Json &warp : warps) {
                debug_identity_add(identity, std::to_string(warp["x"].int_value()));
                debug_identity_add(identity, std::to_string(warp["y"].int_value()));
                debug_identity_add(identity, std::to_string(warp["elevation"].int_value()));
                debug_identity_add(identity, json_to_string(warp, "dest_map"));
                debug_identity_add(identity, json_to_string(warp, "dest_warp_id"));
            }
        }
    }
    return identity;
}

static string generate_debug_map_names_text(const Json &groups_data,
                                            const vector<string> &invalid_maps,
                                            const map<string, string> &map_regions,
                                            uint64_t registry_identity)
{
    ostringstream text;
    vector<bool> group_has_maps;

    text << get_generated_warning("data/maps/map_groups.json", false);
    text << "#ifndef GUARD_GENERATED_DEBUG_MAP_NAMES_H\n";
    text << "#define GUARD_GENERATED_DEBUG_MAP_NAMES_H\n\n";
    text << "#define DEBUG_NAMED_WARP_REGISTRY_IDENTITY { ";
    for (int i = 0; i < 8; i++) {
        if (i != 0)
            text << ", ";
        text << "0x" << std::hex << ((registry_identity >> (i * 8)) & 0xFF) << std::dec;
    }
    text << " }\n\n";

    int group_number = 0;
    for (const Json &group_value : groups_data["group_order"].array_items()) {
        const string group_name = json_to_string(group_value);
        vector<string> valid_maps;
        for (const Json &map_value : groups_data[group_name].array_items()) {
            const string map_name = json_to_string(map_value);
            if (find(invalid_maps.begin(), invalid_maps.end(), map_name) == invalid_maps.end())
                valid_maps.push_back(map_name);
        }

        const bool reviewed_empty_group = group_number == 96
            && group_name == "gMapGroup_IndoorSSAqua" && valid_maps.empty()
            && groups_data[group_name].array_items().empty();
        group_has_maps.push_back(!valid_maps.empty() || reviewed_empty_group);
        text << "static const u8 sDebugMapGroupName_" << group_number << "[] = _(";
        text << '"' << humanize_debug_group_name(group_name) << "\");\n";
        for (size_t map_number = 0; map_number < valid_maps.size(); map_number++) {
            text << "static const u8 sDebugMapName_" << group_number << "_" << map_number << "[] = _(";
            text << '"' << humanize_debug_map_name(valid_maps[map_number]) << "\");\n";
        }
        if (!valid_maps.empty() || reviewed_empty_group) {
            text << "static const u8 *const sDebugMapNames_" << group_number << "[] =\n{\n";
            for (size_t map_number = 0; map_number < valid_maps.size(); map_number++)
                text << "    sDebugMapName_" << group_number << "_" << map_number << ",\n";
            text << "};\n";
            text << "static const RegionId sDebugMapRegions_" << group_number << "[] =\n{\n";
            for (const string &map_name : valid_maps) {
                const auto region = map_regions.find(map_name);
                if (region == map_regions.end())
                    FATAL_ERROR("Map '%s' has no registry-backed region while generating debug names\n", map_name.c_str());
                text << "    " << region->second << ",\n";
            }
            text << "};\n";
        }
        text << "\n";
        group_number++;
    }

    text << "static const u8 *const sDebugMapGroupNames[] =\n{\n";
    for (int i = 0; i < group_number; i++)
        text << "    sDebugMapGroupName_" << i << ",\n";
    text << "};\n\n";

    text << "static const RegionId *const sDebugMapRegions[] =\n{\n";
    for (int i = 0; i < group_number; i++) {
        if (group_has_maps[i])
            text << "    sDebugMapRegions_" << i << ",\n";
        else
            text << "    NULL,\n";
    }
    text << "};\n\n";

    text << "static const u8 *const *const sDebugMapNames[] =\n{\n";
    for (int i = 0; i < group_number; i++) {
        if (group_has_maps[i])
            text << "    sDebugMapNames_" << i << ",\n";
        else
            text << "    NULL,\n";
    }
    text << "};\n\n";
    text << "#endif // GUARD_GENERATED_DEBUG_MAP_NAMES_H\n";
    return text.str();
}

string generate_connections_text(Json groups_data, vector<string> &invalid_maps, string include_path) {
    vector<Json> map_names;

    for (auto &group : groups_data["group_order"].array_items()) {
        for (auto map_name : groups_data[json_to_string(group)].array_items()) {
            string map_name_str = json_to_string(map_name);
            auto it = find(invalid_maps.begin(), invalid_maps.end(), map_name_str);
            if (it == invalid_maps.end())
                map_names.push_back(map_name);
        }
    }

    vector<Json> connections_include_order = groups_data["connections_include_order"].array_items();

    if (connections_include_order.size() > 0)
        sort(map_names.begin(), map_names.end(), [connections_include_order](const Json &a, const Json &b) {
            auto iter_a = find(connections_include_order.begin(), connections_include_order.end(), a);
            if (iter_a == connections_include_order.end())
                iter_a = connections_include_order.begin() + numeric_limits<int>::max();
            auto iter_b = find(connections_include_order.begin(), connections_include_order.end(), b);
            if (iter_b == connections_include_order.end())
                iter_b = connections_include_order.begin() + numeric_limits<int>::max();
            return iter_a < iter_b;
        });

    ostringstream text;

    text << get_generated_warning("data/maps/map_groups.json", true);

    for (Json map_name : map_names)
        text << "\t.include \"" << include_path << "/" <<  json_to_string(map_name) << "/connections.inc\"\n";

    return text.str();
}

string generate_headers_text(Json groups_data, vector<string> &invalid_maps, string include_path) {
    vector<string> map_names;

    for (auto &group : groups_data["group_order"].array_items()) {
        for (auto map_name : groups_data[json_to_string(group)].array_items()) {
            string map_name_str = json_to_string(map_name);
            auto it = find(invalid_maps.begin(), invalid_maps.end(), map_name_str);
            if (it == invalid_maps.end())
                map_names.push_back(json_to_string(map_name));
        }
    }

    ostringstream text;

    text << get_generated_warning("data/maps/map_groups.json", true);

    for (string map_name : map_names)
        text << "\t.include \"" << include_path << "/" << map_name << "/header.inc\"\n";

    return text.str();
}

string generate_events_text(Json groups_data, vector<string> &invalid_maps, string include_path) {
    vector<string> map_names;

    for (auto &group : groups_data["group_order"].array_items()) {
        for (auto map_name : groups_data[json_to_string(group)].array_items()) {

            string map_name_str = json_to_string(map_name);
            auto it = find(invalid_maps.begin(), invalid_maps.end(), map_name_str);
            if (it == invalid_maps.end())
                map_names.push_back(json_to_string(map_name));
        }
    }

    ostringstream text;

    text << get_generated_warning(include_path + "/map_groups.json", true);

    for (string map_name : map_names)
        text << "\t.include \"" << include_path << "/" << map_name << "/events.inc\"\n";

    return text.str();
}

Json parse_required_map_defines(void) {
    string json_err;

    string json_text = read_text_file("tools/mapjson/required_map_defines.json");

    Json json_data = Json::parse(json_text, json_err);
    if (json_data == Json())
        FATAL_ERROR("%s\n", json_err.c_str());
    return json_data;
}

string generate_map_constants_text(string groups_filepath, Json groups_data, vector<string> &valid_map_ids,
                                   const string &map_count_filepath) {
    string file_dir = file_parent(groups_filepath) + sep;

    string guard_name = "CONSTANTS_MAP_GROUPS";
    ostringstream text;
    ostringstream mapCountText;

    text << get_include_guard_start(guard_name) << get_generated_warning("data/maps/map_groups.json", false);

    text << "/*\n * DO NOT MODIFY THIS FILE! It is auto-generated from data/maps/map_groups.json\n */\n\n";

    text << "enum\n{\n";

    int group_num = 0;
    vector<int> map_count_vec; //DEBUG
    for (auto &group : groups_data["group_order"].array_items()) {
        string groupName = json_to_string(group);
        text << "    /* " << groupName << " */\n";
        vector<string> map_ids;
        size_t max_length = 0;

        int map_count = 0; //DEBUG

        for (auto &map_name : groups_data[groupName].array_items()) {
            string map_filepath = file_dir + json_to_string(map_name) + sep + "map.json";
            string err_str;
            Json map_data = Json::parse(read_text_file(map_filepath), err_str);
            if (map_data == Json())
                FATAL_ERROR("%s: %s\n", map_filepath.c_str(), err_str.c_str());
            string id = json_to_string(map_data, "id", true);
            map_ids.push_back(id);
            valid_map_ids.push_back(id);
            if (id.length() > max_length)
                max_length = id.length();
            map_count++; //DEBUG
        }

        int map_id_num = 0;
        for (string map_id : map_ids) {
            text << "    " << map_id << string(max_length - map_id.length(), ' ')
                 << " = (" << map_id_num++ << " | (" << group_num << " << 8)),\n";
        }

        text << "\n";

        group_num++;
        map_count_vec.push_back(map_count); //DEBUG
    }

    text << "};\n\n";

    text << "/* Constants for unused maps */\n";
    int map_id_num = 0;
    int old_map_group = -1;
    Json required_map_defines = parse_required_map_defines();
    map <int, string> filtered_map_defines;
    size_t max_length = 0;
    for (auto required_map_id : required_map_defines["required_maps"].array_items()) {
        string map_id = json_to_string(required_map_id[0]);
        auto it = find(valid_map_ids.begin(), valid_map_ids.end(), map_id);
        int current_map_group = required_map_id[1].int_value();
        if (old_map_group != current_map_group) {
            map_id_num = 0;
        } else {
            map_id_num++;
        }
        if (it == valid_map_ids.end()) {
            filtered_map_defines[(map_id_num + 256 * current_map_group)] = map_id;
            if (map_id.length() > max_length)
                max_length = map_id.length();
        }
        old_map_group = current_map_group;
    }

    for ( const auto &[map_value, map_id]: filtered_map_defines) {
        text << "#define " << map_id << string(max_length - map_id.length(), ' ')
             << "  " << map_value << "\n";
    }

    text << "\n#define MAP_GROUPS_COUNT " << group_num << "\n\n";
    text << get_include_guard_end(guard_name);

    mapCountText << "static const u8 MAP_GROUP_COUNT[] = {"; //DEBUG
    for(int i=0; i<group_num; i++){                          //DEBUG
        mapCountText << map_count_vec[i] << ", ";            //DEBUG
    }                                                        //DEBUG
    mapCountText << "0};\n";                                 //DEBUG
    std::filesystem::create_directories(std::filesystem::path(map_count_filepath).parent_path());
    write_text_file(map_count_filepath, mapCountText.str());

    return text.str();
}

// Output paths are directories with trailing path separators
void process_groups(string groups_filepath, vector<string> &map_filepaths, string output_asm, string output_c,
                    const MapBuildPolicy &policy, const string &include_path = "") {
    output_asm = strip_trailing_separator(output_asm); // Remove separator if existing.
    output_c = strip_trailing_separator(output_c);

    string err;
    Json groups_data = Json::parse(read_text_file(groups_filepath), err);
    vector<string> invalid_maps;
    vector<string> valid_map_ids;
    map<string, string> map_regions;
    map<string, Json> maps_by_name;

    for (const string &filepath : map_filepaths) {
        string err;
        string map_json_text = read_text_file(filepath);
        Json map_data = Json::parse(map_json_text, err);
        if (map_data == Json())
            FATAL_ERROR("Failed to read '%s' while processing groups: %s\n", filepath.c_str(), err.c_str());

        string region = json_to_string(map_data, "region", true);

        if (region.empty())
            region = DefaultRegionName(policy.defaultDialect);
        string map_name = json_to_string(map_data, "name");
        maps_by_name[map_name] = map_data;

        if (!policy.IncludesRegion(region)) {
            invalid_maps.push_back(map_name);
        } else {
            map_regions[map_name] = region;
        }
    }

    if (groups_data == Json())
        FATAL_ERROR("%s\n", err.c_str());

    string groups_text = generate_groups_text(groups_data, invalid_maps);
    string generated_include_path = include_path.empty() ? output_asm : include_path;
    string connections_text = generate_connections_text(groups_data, invalid_maps, generated_include_path);
    string headers_text = generate_headers_text(groups_data, invalid_maps, generated_include_path);
    string events_text = generate_events_text(groups_data, invalid_maps, generated_include_path);
    std::filesystem::path map_count_filepath = std::filesystem::path(output_c) / ".." / ".." / "src" / "data" / "map_group_count.h";
    std::filesystem::path debug_map_names_filepath = std::filesystem::path(output_c) / ".." / ".." / "src" / "data" / "debug_map_names.h";
    string map_header_text = generate_map_constants_text(groups_filepath, groups_data, valid_map_ids,
                                                         map_count_filepath.lexically_normal().string());
    const uint64_t debug_named_warp_identity = generate_debug_named_warp_identity(groups_data, maps_by_name);
    string debug_map_names_text = generate_debug_map_names_text(
        groups_data, invalid_maps, map_regions, debug_named_warp_identity);

    write_text_file(output_asm + sep + "groups.inc", groups_text);
    write_text_file(output_asm + sep + "connections.inc", connections_text);
    write_text_file(output_asm + sep + "headers.inc", headers_text);
    write_text_file(output_asm + sep + "events.inc", events_text);
    write_text_file(output_c + sep + "map_groups.h", map_header_text);
    write_text_file(debug_map_names_filepath.lexically_normal().string(), debug_map_names_text);
}

static void validate_layout_formats(const Json &layouts_data, const MapBuildPolicy &policy);

string generate_layout_headers_text(Json layouts_data, const MapBuildPolicy &policy) {
    ostringstream text;

    text << get_generated_warning("data/layouts/layouts.json", true);

    for (auto &layout : layouts_data["layouts"].array_items()) {
        if (layout == Json::object()) continue;
        if (!std::filesystem::exists(json_to_string(layout, "border_filepath")))
            continue;
        string layout_format = json_to_string(layout, "format");
        if (!policy.IncludesLayout(layout_format))
            continue;
        string layoutName = json_to_string(layout, "name");
        string border_label = layoutName + "_Border";
        string blockdata_label = layoutName + "_Blockdata";
        text << border_label << "::\n"
             << "\t.incbin \"" << json_to_string(layout, "border_filepath") << "\"\n\n"
             << blockdata_label << "::\n"
             << "\t.incbin \"" << json_to_string(layout, "blockdata_filepath") << "\"\n\n"
             << "\t.align 2\n"
             << layoutName << "::\n"
             << "\t.4byte " << json_to_string(layout, "width") << "\n"
             << "\t.4byte " << json_to_string(layout, "height") << "\n"
             << "\t.4byte " << border_label << "\n"
             << "\t.4byte " << blockdata_label << "\n"
             << "\t.4byte " << json_to_string(layout, "primary_tileset") << "\n"
             << "\t.4byte " << json_to_string(layout, "secondary_tileset") << "\n";
        const LayoutFormatSpec format_spec = GetLayoutFormatSpec(layout_format);
        text << "\t.byte " << format_spec.encodedValue << " @ " << format_spec.constant << "\n";

        if (layout_format == "frlg")
        {
            text << "\t.byte " << json_to_string(layout, "border_width") << "\n"
                 << "\t.byte " << json_to_string(layout, "border_height") << "\n"
                 << "\t.byte 0\n";
        }
        else
        {
            text << "\t.2byte 0\n"
                 << "\t.byte 0\n";
        }
        text << "\n";
    }

    return text.str();
}

string generate_layouts_table_text(Json layouts_data, const MapBuildPolicy &policy) {
    ostringstream text;

    text << get_generated_warning("data/layouts/layouts.json", true);

    text << "\t.align 2\n"
         << json_to_string(layouts_data, "layouts_table_label") << "::\n";

    for (auto &layout : layouts_data["layouts"].array_items()) {
        if (!std::filesystem::exists(json_to_string(layout, "border_filepath")))
            continue;
        string layout_format = json_to_string(layout, "format");
        GetLayoutFormatSpec(layout_format);
        if (!policy.IncludesLayout(layout_format)) {
            text << "\t.4byte NULL\n";
        } else {
            string layout_name = json_to_string(layout, "name", true);
            if (layout_name.empty()) layout_name = "NULL";
            text << "\t.4byte " << layout_name << "\n";
        }
    }
    text << "gMapLayoutsEnd::\n";

    return text.str();
}

vector<string> parse_required_layout_defines()
{
    vector<string> v;
    string json_err;

    string json_text = read_text_file("tools/mapjson/required_map_defines.json");

    Json json_data = Json::parse(json_text, json_err);
    if (json_data == Json())
        FATAL_ERROR("%s\n", json_err.c_str());

    for (auto required_layout : json_data["required_layouts"].array_items()) {
        v.push_back(json_to_string(required_layout));
    }

    return v;
}
string generate_layouts_constants_text(Json layouts_data) {
    string guard_name = "CONSTANTS_LAYOUTS";
    ostringstream text;
    vector<string> defined_layouts;
    text << get_include_guard_start(guard_name) << get_generated_warning("data/layouts/layouts.json", false);

    int i = 1;
    for (auto &layout : layouts_data["layouts"].array_items()) {
        if (!std::filesystem::exists(json_to_string(layout, "border_filepath")))
            continue;
        if (layout != Json::object())
        {
            text << "#define " << json_to_string(layout, "id") << " " << i << "\n";
            defined_layouts.push_back(json_to_string(layout, "id"));
        }
        i++;
    }

    text << "\n/* Constants for unused layouts */\n";
    vector<string> required_layout_defines = parse_required_layout_defines();
    vector<string> filtered_layout_defines;
    size_t max_length = 0;
    for (auto &layout : required_layout_defines) {
        auto it = find(defined_layouts.begin(), defined_layouts.end(), layout);
        if (it == defined_layouts.end()) {
            filtered_layout_defines.push_back(layout);
            if (layout.length() > max_length)
                max_length = layout.length();
        }
    }

    for (auto &layout : filtered_layout_defines) {
        text << "#define " << layout << string(max_length - layout.length(), ' ')
             << "  0xFFFF\n";
    }
    text << "\n" << get_include_guard_end(guard_name);

    return text.str();
}

void process_layouts(string layouts_filepath, string output_asm, string output_c, const MapBuildPolicy &policy) {
    output_asm = strip_trailing_separator(output_asm).append(sep);
    output_c = strip_trailing_separator(output_c).append(sep);

    string err;
    Json layouts_data = Json::parse(read_text_file(layouts_filepath), err);

    if (layouts_data == Json())
        FATAL_ERROR("%s\n", err.c_str());

    validate_layout_formats(layouts_data, policy);

    string layout_headers_text = generate_layout_headers_text(layouts_data, policy);
    string layouts_table_text = generate_layouts_table_text(layouts_data, policy);
    string layouts_constants_text = generate_layouts_constants_text(layouts_data);

    write_text_file(output_asm + "layouts.inc", layout_headers_text);
    write_text_file(output_asm + "layouts_table.inc", layouts_table_text);
    write_text_file(output_c + "layouts.h", layouts_constants_text);
}

static vector<string> included_map_ids(const vector<string> &map_filepaths, const MapBuildPolicy &policy)
{
    vector<string> ids;
    for (const string &filepath : map_filepaths) {
        string err;
        Json map_data = Json::parse(read_text_file(filepath), err);
        if (map_data == Json())
            FATAL_ERROR("Failed to read '%s' while selecting maps: %s\n", filepath.c_str(), err.c_str());
        string region = json_to_string(map_data, "region", true);
        if (region.empty())
            region = DefaultRegionName(policy.defaultDialect);
        if (policy.IncludesRegion(region))
            ids.push_back(json_to_string(map_data, "id"));
    }
    return ids;
}

static vector<string> sibling_map_ids(const string &map_filepath, const MapBuildPolicy &policy)
{
    const std::filesystem::path maps_dir = std::filesystem::path(map_filepath).parent_path().parent_path();
    vector<string> map_filepaths;
    std::error_code error;
    for (std::filesystem::directory_iterator it(maps_dir, error), end; !error && it != end; it.increment(error)) {
        const std::filesystem::path candidate = it->path() / "map.json";
        if (std::filesystem::is_regular_file(candidate))
            map_filepaths.push_back(candidate.string());
    }
    if (error)
        FATAL_ERROR("Failed to scan standalone map registry '%s': %s\n",
                    maps_dir.string().c_str(), error.message().c_str());
    return included_map_ids(map_filepaths, policy);
}

static Json read_json_file(const string &filepath, const string &purpose)
{
    string err;
    Json data = Json::parse(read_text_file(filepath), err);
    if (data == Json())
        FATAL_ERROR("Failed to read '%s' while %s: %s\n", filepath.c_str(), purpose.c_str(), err.c_str());
    return data;
}

static void require_product_registry(bool condition, const string &message);

static set<int> persistent_consumer_sections(const Json &compatibility,
                                             const map<string, int> &sectionValuesById)
{
    const vector<string> mandatorySources = {
        "src/data/wild_encounters.json",
        "src/data/heal_locations.json",
        "src/data/region_map/city_map_entries.h",
        "src/battle_setup.c",
        "src/daycare.c",
        "src/heal_location.c",
        "src/battle_arena.c",
        "src/battle_dome.c",
        "src/battle_factory.c",
        "src/battle_frontier.c",
        "src/battle_palace.c",
        "src/battle_pike.c",
        "src/battle_pyramid.c",
        "src/battle_tower.c",
        "src/tv.c",
        "src/save_location.c",
        "src/egg_hatch.c",
        "src/overworld.c",
    };
    const Json::array configuredSources = compatibility["persistent_consumer_sources"].array_items();
    set<string> sourcePaths;
    for (const Json &source : configuredSources)
        sourcePaths.insert(json_to_string(source));
    for (const string &mandatory : mandatorySources)
        require_product_registry(sourcePaths.count(mandatory),
                                 "persistent consumer inventory dropped source '" + mandatory + "'");

    map<string, string> sectionByMapId;
    std::error_code error;
    for (std::filesystem::directory_iterator it("data/maps", error), end;
         !error && it != end; it.increment(error))
    {
        const std::filesystem::path candidate = it->path() / "map.json";
        if (!std::filesystem::is_regular_file(candidate))
            continue;
        const Json mapData = read_json_file(candidate.string(), "indexing persistent location consumers");
        sectionByMapId.emplace(json_to_string(mapData, "id"),
                               json_to_string(mapData, "region_map_section"));
    }
    require_product_registry(!error, "failed to scan map headers for persistent location consumers");

    const std::regex sectionToken("\\bMAPSEC_[A-Z0-9_]+\\b");
    const std::regex mapToken("\\bMAP_[A-Z0-9_]+\\b");
    const set<string> nonSectionTokens = {"MAPSEC_DYNAMIC", "MAPSEC_NONE", "MAPSEC_INVALID"};
    set<int> requiredSections;
    for (const string &sourcePath : sourcePaths)
    {
        require_product_registry(std::filesystem::is_regular_file(sourcePath),
                                 "persistent consumer source is missing: '" + sourcePath + "'");
        const string body = read_text_file(sourcePath);
        for (std::sregex_iterator it(body.begin(), body.end(), sectionToken), end; it != end; ++it)
        {
            const string token = it->str();
            const auto section = sectionValuesById.find(token);
            if (section != sectionValuesById.end())
                requiredSections.insert(section->second);
            else
                require_product_registry(nonSectionTokens.count(token),
                                         "persistent consumer source '" + sourcePath
                                             + "' names unknown map section '" + token + "'");
        }
        for (std::sregex_iterator it(body.begin(), body.end(), mapToken), end; it != end; ++it)
        {
            const auto mapSection = sectionByMapId.find(it->str());
            if (mapSection == sectionByMapId.end())
                continue;
            const auto section = sectionValuesById.find(mapSection->second);
            require_product_registry(section != sectionValuesById.end(),
                                     "persistent consumer map '" + it->str()
                                         + "' has unknown map section '" + mapSection->second + "'");
            requiredSections.insert(section->second);
        }
    }
    return requiredSections;
}

struct MapSectionRegistry
{
    Json::array sections;
    int count;
    vector<int> sectionToSaved;
    vector<int> sectionToMet;
    vector<int> savedToSection;
    vector<int> metToSection;
};

struct ReviewedMapSectionAlias
{
    string id;
    string savedLocation;
    int metLocation;
    string metLocationDisplay;
};

static MapSectionRegistry validate_map_section_registry(
    const string &registryPath = "src/data/region_map/region_map_sections.json",
    const string &compatibilityPath = "src/data/region_map/map_section_compatibility.json")
{
    const Json registry = read_json_file(registryPath,
                                        "validating map-section registry");
    const Json compatibility = read_json_file(compatibilityPath,
                                              "validating map-section compatibility");
    const Json::array sections = registry["map_sections"].array_items();
    const Json::array stable = compatibility["stable_sections"].array_items();
    const Json reviewedCodecs = compatibility["reviewed_codecs"];
    const Json::array reviewedAliases = reviewedCodecs["aliases"].array_items();
    const Json savedCompatibility = compatibility["saved_location"];
    const Json metCompatibility = compatibility["met_location"];
    const int savedInvalid = savedCompatibility["invalid_code"].int_value();
    const int metInvalid = metCompatibility["invalid_code"].int_value();
    const int savedFrozenFirst = savedCompatibility["frozen_round_trip"]["first"].int_value();
    const int savedFrozenLast = savedCompatibility["frozen_round_trip"]["last"].int_value();
    const int metFrozenFirst = metCompatibility["frozen_round_trip"]["first"].int_value();
    const int metFrozenLast = metCompatibility["frozen_round_trip"]["last"].int_value();
    const int savedReservedFirst = savedCompatibility["reserved_codes"]["first"].int_value();
    const int savedReservedLast = savedCompatibility["reserved_codes"]["last"].int_value();
    const int metReservedFirst = metCompatibility["reserved_codes"]["first"].int_value();
    const int metReservedLast = metCompatibility["reserved_codes"]["last"].int_value();
    const int reviewedExactFirst = reviewedCodecs["exact"]["first"].int_value();
    const int reviewedExactLast = reviewedCodecs["exact"]["last"].int_value();
    require_product_registry(compatibility["schema_version"].int_value() == 1,
                             "unsupported map-section compatibility schema");
    require_product_registry(savedInvalid == 0xFF && metInvalid == 0xFC,
                             "compact invalid location codes changed");
    require_product_registry(savedFrozenFirst == 0 && savedFrozenLast == 208
                          && metFrozenFirst == savedFrozenFirst && metFrozenLast == savedFrozenLast,
                             "compact frozen round-trip range changed");
    require_product_registry(savedReservedFirst == savedFrozenLast + 1
                          && savedReservedLast == savedInvalid - 1,
                             "saved-location reserved code range changed");
    require_product_registry(metReservedFirst == metFrozenLast + 1
                          && metReservedLast == metInvalid - 1,
                             "met-location reserved code range changed");
    require_product_registry(!sections.empty(), "map-section registry is empty");
    require_product_registry(stable.size() == 209 && sections.size() >= stable.size(),
                             "frozen map-section compatibility range changed");
    require_product_registry(reviewedCodecs["exact"]["first"].type() == Json::Type::NUMBER
                          && reviewedCodecs["exact"]["last"].type() == Json::Type::NUMBER
                          && reviewedExactFirst == 0 && reviewedExactLast == 251,
                             "reviewed exact map-section codec range changed");
    const vector<ReviewedMapSectionAlias> expectedAliases = {
        {"MAPSEC_JOHTO_VICTORY_ROAD", "MAPSEC_VICTORY_ROAD", 70, "MAPSEC_VICTORY_ROAD"},
        {"MAPSEC_BLACKTHORN_CITY", "MAPSEC_BLACKTHORN_CITY", 249, "MAPSEC_ROUTE_44"},
        {"MAPSEC_ROUTE_45", "MAPSEC_ROUTE_45", 249, "MAPSEC_ROUTE_44"},
        {"MAPSEC_ROUTE_46", "MAPSEC_ROUTE_46", 210, "MAPSEC_ROUTE_29"},
        {"MAPSEC_ICE_PATH", "MAPSEC_ROUTE_44", 249, "MAPSEC_ROUTE_44"},
        {"MAPSEC_DRAGONS_DEN", "MAPSEC_ROUTE_44", 249, "MAPSEC_ROUTE_44"},
        {"MAPSEC_DARK_CAVE", "MAPSEC_ROUTE_31", 215, "MAPSEC_ROUTE_31"},
        {"MAPSEC_ROUTE_26", "MAPSEC_ROUTE_28", 212, "MAPSEC_ROUTE_28"},
        {"MAPSEC_ROUTE_27", "MAPSEC_NEW_BARK_TOWN", 209, "MAPSEC_NEW_BARK_TOWN"},
        {"MAPSEC_TOHJO_FALLS", "MAPSEC_NEW_BARK_TOWN", 209, "MAPSEC_NEW_BARK_TOWN"},
    };
    require_product_registry(reviewedAliases.size() == expectedAliases.size(),
                             "reviewed map-section aliases changed");
    for (size_t i = 0; i < expectedAliases.size(); i++)
    {
        const ReviewedMapSectionAlias &expected = expectedAliases[i];
        const Json &actual = reviewedAliases[i];
        require_product_registry(json_to_string(actual, "id") == expected.id
                              && json_to_string(actual, "saved_location") == expected.savedLocation
                              && actual["met_location"].type() == Json::Type::NUMBER
                              && actual["met_location"].int_value() == expected.metLocation
                              && json_to_string(actual, "met_location_display") == expected.metLocationDisplay,
                                 "reviewed map-section aliases changed at index " + std::to_string(i));
    }

    set<string> ids;
    set<int> values;
    map<string, int> valuesById;
    int maximum = -1;
    for (const Json &section : sections)
    {
        const string id = json_to_string(section, "id");
        const int value = section["value"].int_value();
        const string kind = json_to_string(section, "kind");
        const string region = json_to_string(section, "region");
        const string presentation = json_to_string(section, "region_map_type");
        require_product_registry(section["value"].type() == Json::Type::NUMBER && value >= 0 && value < 0xFFFF,
                                 "map section '" + id + "' has invalid value");
        require_product_registry(kind == "geographic" || kind == "special" || kind == "reserved",
                                 "map section '" + id + "' has unknown kind '" + kind + "'");
        require_product_registry(region == "REGION_HOENN" || region == "REGION_KANTO" || region == "REGION_JOHTO",
                                 "map section '" + id + "' has unknown region '" + region + "'");
        require_product_registry(presentation == "REGION_MAP_HOENN" || presentation == "REGION_MAP_KANTO"
                              || presentation == "REGION_MAP_SEVII123" || presentation == "REGION_MAP_SEVII45"
                              || presentation == "REGION_MAP_SEVII67",
                                 "map section '" + id + "' has unknown region-map presentation");
        require_product_registry(ids.insert(id).second, "duplicate map-section id '" + id + "'");
        require_product_registry(values.insert(value).second,
                                 "duplicate map-section value " + std::to_string(value));
        valuesById.emplace(id, value);
        maximum = std::max(maximum, value);
    }

    const set<int> consumerSections = persistent_consumer_sections(compatibility, valuesById);

    set<int> reservedValues;
    for (const Json &reserved : compatibility["reserved_map_section_values"].array_items())
    {
        const int value = reserved.int_value();
        require_product_registry(reserved.type() == Json::Type::NUMBER && value >= 0 && value < 0xFFFF,
                                 "reserved map-section value is outside the world-ID domain");
        require_product_registry(!values.count(value),
                                 "reserved map-section value is still assigned: " + std::to_string(value));
        require_product_registry(reservedValues.insert(value).second,
                                 "duplicate reserved map-section value " + std::to_string(value));
    }
    for (int value = 0; value <= maximum; value++)
        require_product_registry(values.count(value) || reservedValues.count(value),
                                 "unmarked map-section value gap " + std::to_string(value));
    require_product_registry(registry["map_section_count"].int_value() == maximum + 1,
                             "map_section_count does not cover the complete world-ID domain");

    vector<int> savedToSection(256, -1);
    vector<int> metToSection(256, -1);
    vector<int> sectionToSaved(maximum + 1, -1);
    vector<int> sectionToMet(maximum + 1, -1);
    for (const Json &section : sections)
    {
        const string id = json_to_string(section, "id");
        const int value = section["value"].int_value();
        const Json &savedValue = section["saved_location"];
        if (!savedValue.is_null())
        {
            const string savedTarget = json_to_string(section, "saved_location");
            const auto saved = valuesById.find(savedTarget);
            require_product_registry(saved != valuesById.end(),
                                     "map section '" + id + "' has unknown saved-location target '" + savedTarget + "'");
            require_product_registry(saved->second >= 0 && saved->second < savedInvalid,
                                     "map section '" + id + "' saved-location mapping collides with invalid sentinel");
            require_product_registry(savedToSection[saved->second] == -1 || savedToSection[saved->second] == saved->second,
                                     "conflicting saved-location reverse target code " + std::to_string(saved->second)
                                         + " for map section '" + id + "'");
            savedToSection[saved->second] = saved->second;
            sectionToSaved[value] = saved->second;
        }

        const Json &metValue = section["met_location"];
        const Json &metDisplayValue = section["met_location_display"];
        require_product_registry(metValue.is_null() == metDisplayValue.is_null(),
                                 "map section '" + id + "' has a partial met-location mapping");
        if (!metValue.is_null())
        {
            const int metCode = metValue.int_value();
            const string metDisplay = json_to_string(section, "met_location_display");
            const auto metDisplayTarget = valuesById.find(metDisplay);
            require_product_registry(metValue.type() == Json::Type::NUMBER && metCode >= 0 && metCode < metInvalid,
                                     "map section '" + id + "' met-location mapping collides with reserved origin");
            require_product_registry(metDisplayTarget != valuesById.end(),
                                     "map section '" + id + "' has unknown met-location display target '" + metDisplay + "'");
            require_product_registry(metToSection[metCode] == -1 || metToSection[metCode] == metDisplayTarget->second,
                                     "conflicting met-location reverse target code " + std::to_string(metCode)
                                         + " for map section '" + id + "'");
            metToSection[metCode] = metDisplayTarget->second;
            sectionToMet[value] = metCode;
        }
    }

    map<string, Json> reviewedAliasesById;
    for (const Json &alias : reviewedAliases)
    {
        const string id = json_to_string(alias, "id");
        require_product_registry(reviewedAliasesById.emplace(id, alias).second,
                                 "duplicate reviewed map-section alias '" + id + "'");
    }
    for (const Json &section : sections)
    {
        const string id = json_to_string(section, "id");
        const int value = section["value"].int_value();
        const Json &savedValue = section["saved_location"];
        const Json &metValue = section["met_location"];
        const bool hasSavedAlias = !savedValue.is_null() && json_to_string(section, "saved_location") != id;
        const bool hasMetAlias = !metValue.is_null()
            && (metValue.int_value() != value || json_to_string(section, "met_location_display") != id);
        const auto reviewedAliasIt = reviewedAliasesById.find(id);
        const bool reviewedAlias = reviewedAliasIt != reviewedAliasesById.end();

        require_product_registry(!hasSavedAlias || reviewedAlias,
                                 "map section '" + id + "' uses an unreviewed saved-location fallback");
        require_product_registry(!hasMetAlias || reviewedAlias,
                                 "map section '" + id + "' uses an unreviewed met-location fallback");
        require_product_registry(!reviewedAlias || (!savedValue.is_null()
                                                  && !metValue.is_null()
                                                  && (hasSavedAlias || hasMetAlias)),
                                 "reviewed alias '" + id + "' has an incomplete persistence codec");
        if (reviewedAlias)
        {
            const Json &reviewed = reviewedAliasIt->second;
            require_product_registry(json_to_string(section, "saved_location")
                                      == json_to_string(reviewed, "saved_location")
                                  && metValue.type() == Json::Type::NUMBER
                                  && metValue.int_value() == reviewed["met_location"].int_value()
                                  && json_to_string(section, "met_location_display")
                                      == json_to_string(reviewed, "met_location_display"),
                                     "reviewed alias '" + id
                                         + "' does not match its reviewed persistence codec");
        }
        if (value >= reviewedExactFirst && value <= reviewedExactLast)
        {
            require_product_registry(!savedValue.is_null() && json_to_string(section, "saved_location") == id
                                  && !metValue.is_null() && metValue.type() == Json::Type::NUMBER
                                  && metValue.int_value() == value
                                  && json_to_string(section, "met_location_display") == id,
                                     "gameplay-relevant section '" + id + "' has an incomplete persistence codec");
        }
        if (reviewedAlias)
        {
            const string savedTarget = json_to_string(section, "saved_location");
            const string metTarget = json_to_string(section, "met_location_display");
            const int savedCode = valuesById.at(savedTarget);
            const int metTargetValue = valuesById.at(metTarget);
            const int metCode = metValue.int_value();
            require_product_registry(sectionToSaved.at(savedCode) == savedCode
                                  && savedToSection.at(savedCode) == savedCode,
                                     "reviewed alias '" + id
                                         + "' lacks a canonical saved-location reverse owner");
            require_product_registry(sectionToMet.at(metTargetValue) == metCode
                                  && metToSection.at(metCode) == metTargetValue,
                                     "reviewed alias '" + id
                                         + "' lacks a canonical met-location reverse owner");
        }
    }

    for (int value : consumerSections)
    {
        const string id = json_to_string(sections.at(value), "id");
        require_product_registry(sectionToSaved.at(value) >= 0 && sectionToMet.at(value) >= 0,
                                 "persistent consumer section '" + id
                                     + "' has an incomplete persistence codec");
        require_product_registry((sectionToSaved.at(value) == value
                               && sectionToMet.at(value) == value)
                              || reviewedAliasesById.count(id),
                                 "persistent consumer section '" + id
                                     + "' lacks an exact or reviewed persistence codec");
    }

    for (size_t i = 0; i < stable.size(); i++)
    {
        require_product_registry(json_to_string(stable[i], "id") == json_to_string(sections[i], "id")
                              && stable[i]["value"].int_value() == sections[i]["value"].int_value(),
                                 "map-section compatibility manifest changed at index " + std::to_string(i));
    }
    for (int value = savedFrozenFirst; value <= savedFrozenLast; value++)
        require_product_registry(savedToSection[value] == value && metToSection[value] == value,
                                 "map-section compact round trip changed for " + std::to_string(value));
    require_product_registry(metCompatibility["special_origins"]["egg"].int_value() == metInvalid + 1
                          && metCompatibility["special_origins"]["in_game_trade"].int_value() == metInvalid + 2
                          && metCompatibility["special_origins"]["fateful_encounter"].int_value() == 0xFF,
                             "reserved met-location origins changed");
    return {sections, maximum + 1, sectionToSaved, sectionToMet, savedToSection, metToSection};
}

static void write_map_section_metadata(const std::filesystem::path &staging)
{
    const MapSectionRegistry registry = validate_map_section_registry();
    const std::filesystem::path includeDir = staging / "include" / "generated";
    const std::filesystem::path sourceDir = staging / "src" / "data";
    std::filesystem::create_directories(includeDir);
    std::filesystem::create_directories(sourceDir);

    ostringstream header;
    header << get_generated_warning("src/data/region_map/region_map_sections.json", false)
           << "#ifndef GUARD_GENERATED_MAP_SECTION_METADATA_H\n"
           << "#define GUARD_GENERATED_MAP_SECTION_METADATA_H\n\n"
           << "#define GENERATED_MAP_SECTION_COUNT " << registry.count << "\n\n"
           << "extern const MapSectionId gSavedLocationToMapSection[256];\n"
           << "extern const MapSectionId gMetLocationToMapSection[256];\n\n"
           << "#endif /* GUARD_GENERATED_MAP_SECTION_METADATA_H */\n";
    write_text_file((includeDir / "map_section_metadata.h").string(), header.str());

    ostringstream source;
    source << get_generated_warning("src/data/region_map/region_map_sections.json", false);
    map<int, Json> sectionsByValue;
    for (const Json &section : registry.sections)
        sectionsByValue.emplace(section["value"].int_value(), section);
    source << "const struct MapSectionMetadata gMapSectionMetadata[MAPSEC_COUNT] =\n{\n";
    for (int value = 0; value < registry.count; value++)
    {
        const auto found = sectionsByValue.find(value);
        if (found == sectionsByValue.end())
        {
            source << "    [" << value << "] = {REGION_NONE, MAP_SECTION_KIND_RESERVED, 0xFF, 0},\n";
            continue;
        }
        const Json &section = found->second;
        const string kind = json_to_string(section, "kind");
        source << "    [" << json_to_string(section, "id") << "] = {"
               << json_to_string(section, "region") << ", "
               << (kind == "geographic" ? "MAP_SECTION_KIND_GEOGRAPHIC" : kind == "special" ? "MAP_SECTION_KIND_SPECIAL" : "MAP_SECTION_KIND_RESERVED")
               << ", " << json_to_string(section, "region_map_type") << ", 0},\n";
    }
    source << "};\n\nconst SavedLocationCode gMapSectionToSavedLocation[MAPSEC_COUNT] =\n{\n";
    for (int value = 0; value < registry.count; value++)
        source << "    [" << value << "] = "
               << (registry.sectionToSaved[value] < 0 ? "SAVED_LOCATION_INVALID" : std::to_string(registry.sectionToSaved[value])) << ",\n";
    source << "};\n\nconst MetLocationCode gMapSectionToMetLocation[MAPSEC_COUNT] =\n{\n";
    for (int value = 0; value < registry.count; value++)
        source << "    [" << value << "] = "
               << (registry.sectionToMet[value] < 0 ? "MET_LOCATION_INVALID" : std::to_string(registry.sectionToMet[value])) << ",\n";

    source << "};\n";
    write_text_file((sourceDir / "map_section_metadata.inc.c").string(), source.str());
}

static void require_product_registry(bool condition, const string &message)
{
    if (!condition)
        FATAL_ERROR("All-regions registry contract failed: %s\n", message.c_str());
}

struct TilesetDependency
{
    string tiles;
    string palettes;
    string metatiles;
    string metatileAttributes;
    string callback;
    string attributeFormat;
};

static string parse_tileset_field(const string &owner, const string &body, const string &field)
{
    std::regex field_regex("\\." + field + "\\s*=\\s*([A-Za-z_][A-Za-z0-9_]*|0)\\s*,");
    std::smatch match;
    require_product_registry(std::regex_search(body, match, field_regex),
                             "tileset '" + owner + "' lacks ." + field);
    return match[1].str();
}

static string parse_tileset_attribute_format(const string &owner, const string &body)
{
    const std::regex flags_regex("\\.flags\\s*=\\s*TILESET_FLAGS\\s*\\(\\s*(?:TRUE|FALSE)\\s*,\\s*(METATILE_ATTRIBUTES_(?:EMERALD_U16|FRLG_U32))\\s*\\)\\s*,");
    std::smatch match;
    require_product_registry(std::regex_search(body, match, flags_regex),
                             "tileset '" + owner + "' lacks an explicit attribute format");
    return match[1].str();
}

static map<string, TilesetDependency> parse_tileset_dependencies()
{
    const string headers = read_text_file("src/data/tilesets/headers.h");
    const std::regex tileset_regex("const\\s+struct\\s+Tileset\\s+(gTileset_[A-Za-z0-9_]+)\\s*=\\s*\\{([\\s\\S]*?)\\};");
    map<string, TilesetDependency> dependencies;
    for (std::sregex_iterator it(headers.begin(), headers.end(), tileset_regex), end; it != end; ++it) {
        const string name = (*it)[1].str();
        const string body = (*it)[2].str();
        dependencies.emplace(name, TilesetDependency {
            parse_tileset_field(name, body, "tiles"),
            parse_tileset_field(name, body, "palettes"),
            parse_tileset_field(name, body, "metatiles"),
            parse_tileset_field(name, body, "metatileAttributes"),
            parse_tileset_field(name, body, "callback"),
            parse_tileset_attribute_format(name, body),
        });
    }
    require_product_registry(!dependencies.empty(), "no tileset dependencies parsed");
    return dependencies;
}

static map<string, string> parse_metatile_blob_paths()
{
    const string declarations = read_text_file("src/data/tilesets/metatiles.h");
    const std::regex declaration_regex("const\\s+u16\\s+([A-Za-z_][A-Za-z0-9_]*)\\[\\]\\s*=\\s*INCBIN_U16\\(\"([^\"]+)\"\\)");
    map<string, string> paths;

    for (std::sregex_iterator it(declarations.begin(), declarations.end(), declaration_regex), end; it != end; ++it)
        paths.emplace((*it)[1].str(), (*it)[2].str());
    require_product_registry(!paths.empty(), "no metatile blob declarations parsed");
    return paths;
}

static string derive_tileset_attribute_format(const string &tileset_name,
                                               const TilesetDependency &tileset,
                                               const map<string, string> &blob_paths)
{
    const auto metatiles_path = blob_paths.find(tileset.metatiles);
    const auto attributes_path = blob_paths.find(tileset.metatileAttributes);
    require_product_registry(metatiles_path != blob_paths.end(),
                             "tileset '" + tileset_name + "' has unknown metatile blob '" + tileset.metatiles + "'");
    require_product_registry(attributes_path != blob_paths.end(),
                             "tileset '" + tileset_name + "' has unknown attribute blob '" + tileset.metatileAttributes + "'");

    std::error_code error;
    const uintmax_t metatiles_size = std::filesystem::file_size(metatiles_path->second, error);
    require_product_registry(!error, "cannot size metatile blob '" + metatiles_path->second + "'");
    const uintmax_t attributes_size = std::filesystem::file_size(attributes_path->second, error);
    require_product_registry(!error, "cannot size attribute blob '" + attributes_path->second + "'");
    require_product_registry(metatiles_size != 0 && metatiles_size % 16 == 0,
                             "tileset '" + tileset_name + "' has malformed metatile blob width");

    const uintmax_t metatile_count = metatiles_size / 16;
    if (attributes_size == metatile_count * 2)
        return "METATILE_ATTRIBUTES_EMERALD_U16";
    if (attributes_size == metatile_count * 4)
        return "METATILE_ATTRIBUTES_FRLG_U32";
    FATAL_ERROR("tileset '%s' attribute blob width is neither u16 nor u32\n", tileset_name.c_str());
}

static void validate_layout_formats(const Json &layouts_data, const MapBuildPolicy &policy)
{
    const map<string, TilesetDependency> tilesets = parse_tileset_dependencies();
    const map<string, string> blob_paths = parse_metatile_blob_paths();
    map<string, string> derived_formats;

    for (const auto &entry : tilesets)
    {
        const string derived = derive_tileset_attribute_format(entry.first, entry.second, blob_paths);
        require_product_registry(entry.second.attributeFormat == derived,
                                 "tileset '" + entry.first + "' declares " + entry.second.attributeFormat
                                 + " but its blobs derive " + derived);
        derived_formats.emplace(entry.first, derived);
    }

    for (const Json &layout : layouts_data["layouts"].array_items())
    {
        const string format = json_to_string(layout, "format");
        GetLayoutFormatSpec(format);
        if (!policy.IncludesLayout(format))
            continue;

        const string layout_name = json_to_string(layout, "name");
        const string primary = json_to_string(layout, "primary_tileset");
        const string secondary = json_to_string(layout, "secondary_tileset");
        const auto primary_format = derived_formats.find(primary);
        const auto secondary_format = derived_formats.find(secondary);
        require_product_registry(primary_format != derived_formats.end(),
                                 "layout '" + layout_name + "' references unknown primary tileset '" + primary + "'");
        require_product_registry(secondary == "0" || secondary_format != derived_formats.end(),
                                 "layout '" + layout_name + "' references unknown secondary tileset '" + secondary + "'");

        if (format != "johto")
        {
            const string expected = format == "frlg"
                ? "METATILE_ATTRIBUTES_FRLG_U32"
                : "METATILE_ATTRIBUTES_EMERALD_U16";
            require_product_registry(primary_format->second == expected,
                                     "layout '" + layout_name + "' format '" + format
                                     + "' mismatches primary tileset attribute width");
            require_product_registry(secondary == "0" || secondary_format->second == expected,
                                     "layout '" + layout_name + "' format '" + format
                                     + "' mismatches secondary tileset attribute width");
        }
    }
}

static int map_battle_scene_value(const string &name)
{
    static const map<string, int> values = {
        {"MAP_BATTLE_SCENE_NORMAL", 0},
        {"MAP_BATTLE_SCENE_GYM", 1},
        {"MAP_BATTLE_SCENE_MAGMA", 2},
        {"MAP_BATTLE_SCENE_AQUA", 3},
        {"MAP_BATTLE_SCENE_SIDNEY", 4},
        {"MAP_BATTLE_SCENE_PHOEBE", 5},
        {"MAP_BATTLE_SCENE_GLACIA", 6},
        {"MAP_BATTLE_SCENE_DRAKE", 7},
        {"MAP_BATTLE_SCENE_FRONTIER", 8},
        {"MAP_BATTLE_SCENE_INDOOR_1", 0},
        {"MAP_BATTLE_SCENE_INDOOR_2", 0},
        {"MAP_BATTLE_SCENE_LORELEI", 0},
        {"MAP_BATTLE_SCENE_BRUNO", 0},
        {"MAP_BATTLE_SCENE_AGATHA", 0},
        {"MAP_BATTLE_SCENE_LANCE", 0},
        {"MAP_BATTLE_SCENE_LINK", 0},
    };
    const auto found = values.find(name);
    if (found == values.end())
        FATAL_ERROR("unknown map battle scene '%s'\n", name.c_str());
    return found->second;
}

static int section_region_value(const string &name)
{
    if (name == "REGION_KANTO") return 1;
    if (name == "REGION_JOHTO") return 2;
    if (name == "REGION_HOENN") return 3;
    FATAL_ERROR("unknown map-section region '%s'\n", name.c_str());
}

static int section_kind_value(const string &name)
{
    if (name == "geographic") return 0;
    if (name == "special") return 1;
    if (name == "reserved") return 2;
    FATAL_ERROR("unknown map-section kind '%s'\n", name.c_str());
}

static int region_map_type_value(const string &name)
{
    static const map<string, int> values = {
        {"REGION_MAP_HOENN", 0},
        {"REGION_MAP_KANTO", 1},
        {"REGION_MAP_SEVII123", 2},
        {"REGION_MAP_SEVII45", 3},
        {"REGION_MAP_SEVII67", 4},
    };
    const auto found = values.find(name);
    if (found == values.end())
        FATAL_ERROR("unknown region-map type '%s'\n", name.c_str());
    return found->second;
}

struct SurfEdgeExitRecord
{
    string sourceName;
    string sourceId;
    int sourceGroup;
    int sourceNumber;
    string targetName;
    string targetId;
    int targetGroup;
    int targetNumber;
    int targetX;
    int targetY;
    string exitEdge;
    int exitEdgeValue;
    string targetFacing;
    int targetFacingValue;
    string routeProfile;
    int routeProfileValue;
};

struct SurfEdgeMapIdentity
{
    string name;
    string id;
    string region;
    string layoutId;
    int group;
    int number;
};

static int surf_edge_direction_value(const string &direction)
{
    if (direction == "south") return 1;
    if (direction == "north") return 2;
    if (direction == "west") return 3;
    if (direction == "east") return 4;
    return -1;
}

static string surf_edge_direction_constant(const string &direction)
{
    if (direction == "south") return "DIR_SOUTH";
    if (direction == "north") return "DIR_NORTH";
    if (direction == "west") return "DIR_WEST";
    if (direction == "east") return "DIR_EAST";
    FATAL_ERROR("unknown Surf edge direction '%s'\n", direction.c_str());
}

static int surf_edge_route_profile_value(const string &profile)
{
    if (profile.empty()) return 0;
    if (profile == "generated_ocean") return 1;
    return -1;
}

static string surf_edge_route_profile_constant(const string &profile)
{
    if (profile == "generated_ocean") return "SURF_EDGE_ROUTE_PROFILE_GENERATED_OCEAN";
    FATAL_ERROR("unknown Surf edge route profile '%s'\n", profile.c_str());
}

static string connection_edge_name(const string &direction)
{
    if (direction == "up") return "north";
    if (direction == "down") return "south";
    if (direction == "left") return "west";
    if (direction == "right") return "east";
    return "";
}

static int strict_nonnegative_coordinate(const Json &exit, const string &mapName,
                                         const string &field)
{
    const Json &value = exit[field];
    require_product_registry(value.type() == Json::Type::NUMBER
                          && std::isfinite(value.number_value())
                          && std::floor(value.number_value()) == value.number_value(),
                             "map '" + mapName + "' Surf edge exit field '" + field
                                 + "' must be an integer");
    require_product_registry(value.number_value() >= 0 && value.number_value() <= 32767,
                             "map '" + mapName + "' Surf edge exit field '" + field
                                 + "' is outside the nonnegative signed 16-bit range");
    return value.int_value();
}

static vector<SurfEdgeExitRecord> normalize_surf_edge_exits(
    const MapBuildPolicy &policy, const Json &groupsData, const Json &layoutsData,
    const vector<string> &mapFilepaths)
{
    map<string, Json> mapsByName;
    map<string, string> mapNamesById;
    for (const string &filepath : mapFilepaths) {
        const Json mapData = read_json_file(filepath, "validating Surf edge exits");
        const string name = json_to_string(mapData, "name");
        const string id = json_to_string(mapData, "id");
        require_product_registry(mapsByName.emplace(name, mapData).second,
                                 "duplicate reviewed map name '" + name + "'");
        require_product_registry(mapNamesById.emplace(id, name).second,
                                 "duplicate reviewed map id '" + id + "'");
    }

    map<string, SurfEdgeMapIdentity> identities;
    int group = 0;
    for (const Json &groupValue : groupsData["group_order"].array_items()) {
        const string groupName = json_to_string(groupValue);
        int number = 0;
        for (const Json &mapValue : groupsData[groupName].array_items()) {
            const string name = json_to_string(mapValue);
            const auto found = mapsByName.find(name);
            require_product_registry(found != mapsByName.end(),
                                     "map group names missing map '" + name + "'");
            const Json &mapData = found->second;
            require_product_registry(identities.emplace(name, SurfEdgeMapIdentity {
                name, json_to_string(mapData, "id"), json_to_string(mapData, "region"),
                json_to_string(mapData, "layout"), group, number
            }).second, "map '" + name + "' appears in more than one group");
            number++;
        }
        group++;
    }

    struct LayoutBounds { int width; int height; string format; };
    map<string, LayoutBounds> layoutBounds;
    for (const Json &layout : layoutsData["layouts"].array_items()) {
        const string id = json_to_string(layout, "id");
        require_product_registry(layout["width"].type() == Json::Type::NUMBER
                              && layout["height"].type() == Json::Type::NUMBER
                              && layout["width"].number_value() > 0
                              && layout["height"].number_value() > 0
                              && std::floor(layout["width"].number_value()) == layout["width"].number_value()
                              && std::floor(layout["height"].number_value()) == layout["height"].number_value(),
                                 "layout '" + id + "' has invalid Surf edge exit bounds");
        require_product_registry(layoutBounds.emplace(id, LayoutBounds {
            layout["width"].int_value(), layout["height"].int_value(),
            json_to_string(layout, "format")
        }).second, "duplicate layout id '" + id + "'");
    }

    vector<SurfEdgeExitRecord> records;
    const set<string> requiredFields = {
        "exit_edge", "target_map", "target_x", "target_y", "target_facing"
    };
    const set<string> profiledFields = {
        "exit_edge", "target_map", "target_x", "target_y", "target_facing", "route_profile"
    };
    for (const auto &[sourceName, mapData] : mapsByName) {
        const bool hasDeclarations = mapData.object_items().find("edge_exits")
                                  != mapData.object_items().end();
        const Json &declarations = mapData["edge_exits"];
        require_product_registry(!hasDeclarations || declarations.type() == Json::Type::ARRAY,
                                 "map '" + sourceName + "' edge_exits must be an array");
        if (!hasDeclarations)
            continue;
        const auto source = identities.find(sourceName);
        require_product_registry(source != identities.end(),
                                 "ungrouped map '" + sourceName + "' declares a Surf edge exit");
        set<string> sourceEdges;
        for (const Json &declaration : declarations.array_items()) {
            require_product_registry(declaration.type() == Json::Type::OBJECT,
                                     "map '" + sourceName + "' Surf edge exit must be an object");
            set<string> actualFields;
            for (const auto &[field, unused] : declaration.object_items())
                actualFields.insert(field);
            require_product_registry(actualFields == requiredFields || actualFields == profiledFields,
                                     "map '" + sourceName + "' Surf edge exit must contain exactly exit_edge, target_map, target_x, target_y, target_facing, and optional route_profile");

            require_product_registry(declaration["exit_edge"].type() == Json::Type::STRING,
                                     "map '" + sourceName + "' Surf edge exit field 'exit_edge' must be a string");
            require_product_registry(declaration["target_map"].type() == Json::Type::STRING,
                                     "map '" + sourceName + "' Surf edge exit field 'target_map' must be a string");
            require_product_registry(declaration["target_facing"].type() == Json::Type::STRING,
                                     "map '" + sourceName + "' Surf edge exit field 'target_facing' must be a string");
            require_product_registry(actualFields != profiledFields
                                  || declaration["route_profile"].type() == Json::Type::STRING,
                                     "map '" + sourceName + "' Surf edge exit field 'route_profile' must be a string");
            const string routeProfile = actualFields == profiledFields
                                      ? json_to_string(declaration, "route_profile")
                                      : "";
            const int routeProfileValue = surf_edge_route_profile_value(routeProfile);
            require_product_registry(routeProfileValue >= 0,
                                     "map '" + sourceName + "' Surf edge exit has invalid route profile '" + routeProfile + "'");
            const string edge = declaration["exit_edge"].string_value();
            const string targetId = declaration["target_map"].string_value();
            const string facing = declaration["target_facing"].string_value();
            const int edgeValue = surf_edge_direction_value(edge);
            const int facingValue = surf_edge_direction_value(facing);
            require_product_registry(edgeValue >= 0,
                                     "map '" + sourceName + "' Surf edge exit has invalid edge '" + edge + "'");
            require_product_registry(facingValue >= 0,
                                     "map '" + sourceName + "' Surf edge exit has invalid facing '" + facing + "'");
            require_product_registry(sourceEdges.insert(edge).second,
                                     "map '" + sourceName + "' has duplicate Surf edge '" + edge + "'");
            const auto targetName = mapNamesById.find(targetId);
            require_product_registry(targetName != mapNamesById.end(),
                                     "map '" + sourceName + "' Surf edge exit names unknown target map id '" + targetId + "'");
            const auto target = identities.find(targetName->second);
            require_product_registry(target != identities.end(),
                                     "map '" + sourceName + "' Surf edge exit names ungrouped target map '" + targetName->second + "'");
            for (const Json &connection : mapData["connections"].array_items()) {
                require_product_registry(connection_edge_name(json_to_string(connection, "direction")) != edge,
                                         "map '" + sourceName + "' Surf edge '" + edge
                                             + "' conflicts with an authored cardinal connection");
            }
            const int x = strict_nonnegative_coordinate(declaration, sourceName, "target_x");
            const int y = strict_nonnegative_coordinate(declaration, sourceName, "target_y");
            const auto bounds = layoutBounds.find(target->second.layoutId);
            require_product_registry(bounds != layoutBounds.end(),
                                     "Surf edge target map '" + target->second.name + "' names unknown layout '"
                                         + target->second.layoutId + "'");
            require_product_registry(x < bounds->second.width && y < bounds->second.height,
                                     "map '" + sourceName + "' Surf edge target coordinates are outside map '"
                                         + target->second.name + "'");

            const auto sourceBounds = layoutBounds.find(source->second.layoutId);
            require_product_registry(sourceBounds != layoutBounds.end(),
                                     "Surf edge source map '" + sourceName + "' names unknown layout '"
                                         + source->second.layoutId + "'");
            const bool active = policy.IncludesRegion(source->second.region)
                             && policy.IncludesRegion(target->second.region)
                             && policy.IncludesLayout(sourceBounds->second.format)
                             && policy.IncludesLayout(bounds->second.format);
            if (active) {
                records.push_back({
                    source->second.name, source->second.id, source->second.group, source->second.number,
                    target->second.name, target->second.id, target->second.group, target->second.number,
                    x, y, edge, edgeValue, facing, facingValue, routeProfile, routeProfileValue,
                });
            }
        }
    }
    sort(records.begin(), records.end(), [](const SurfEdgeExitRecord &left,
                                            const SurfEdgeExitRecord &right) {
        if (left.sourceGroup != right.sourceGroup) return left.sourceGroup < right.sourceGroup;
        if (left.sourceNumber != right.sourceNumber) return left.sourceNumber < right.sourceNumber;
        return left.exitEdgeValue < right.exitEdgeValue;
    });
    return records;
}

static void write_surf_edge_exit_registry(const std::filesystem::path &staging,
                                          const vector<SurfEdgeExitRecord> &records)
{
    const std::filesystem::path output = staging / "src" / "data" / "surf_edge_exits.inc.c";
    std::filesystem::create_directories(output.parent_path());
    ostringstream text;
    text << get_generated_warning("data/maps/*/map.json edge_exits", false)
         << "const struct SurfEdgeExit gSurfEdgeExits[] =\n{\n";
    if (records.empty()) {
        text << "    {0},\n";
    } else {
        for (const SurfEdgeExitRecord &record : records) {
            text << "    { " << record.sourceId << ", " << record.targetId << ", "
                 << record.targetX << ", " << record.targetY << ", "
                 << surf_edge_direction_constant(record.exitEdge) << ", "
                 << surf_edge_direction_constant(record.targetFacing) << " },\n";
        }
    }
    text << "};\n\nconst u16 gSurfEdgeExitCount = " << records.size() << ";\n";
    text << "\nconst struct SurfEdgeRouteProfile gSurfEdgeRouteProfiles[] =\n{\n";
    bool wroteProfile = false;
    size_t profileCount = 0;
    for (const SurfEdgeExitRecord &record : records) {
        if (record.routeProfileValue != 0) {
            text << "    { " << record.sourceId << ", "
                 << surf_edge_direction_constant(record.exitEdge) << ", "
                 << surf_edge_route_profile_constant(record.routeProfile) << " },\n";
            wroteProfile = true;
            profileCount++;
        }
    }
    if (!wroteProfile)
        text << "    {0},\n";
    text << "};\n\nconst u16 gSurfEdgeRouteProfileCount = " << profileCount << ";\n";
    write_text_file(output.string(), text.str());
}

static void write_integrity_manifest(const std::filesystem::path &staging,
                                      const MapBuildPolicy &policy,
                                      const string &groups_filepath,
                                      const string &layouts_filepath,
                                      const vector<string> &map_filepaths,
                                      const vector<SurfEdgeExitRecord> &surfEdgeExits)
{
    const Json groups_data = read_json_file(groups_filepath, "building the integrity manifest");
    const Json layouts_data = read_json_file(layouts_filepath, "building the integrity manifest");
    const MapSectionRegistry sectionRegistry = validate_map_section_registry();
    map<string, int> sectionValues;
    for (const Json &section : sectionRegistry.sections)
        sectionValues.emplace(json_to_string(section, "id"), section["value"].int_value());
    map<string, Json> maps_by_name;
    map<string, int> region_counts;
    set<string> reviewed_names;

    for (const string &filepath : map_filepaths) {
        Json map_data = read_json_file(filepath, "building the integrity manifest");
        const string name = json_to_string(map_data, "name");
        require_product_registry(maps_by_name.emplace(name, map_data).second,
                                 "duplicate reviewed map name '" + name + "'");
        reviewed_names.insert(name);
        region_counts[json_to_string(map_data, "region")]++;
    }

    Json::array group_records;
    Json::array map_records;
    Json::array layout_records;
    Json::array tileset_records;
    Json::array exclusion_records;
    Json::array section_metadata_records;
    set<string> grouped_names;
    set<string> required_symbols;
    set<string> used_tilesets;
    map<int, Json> sections_by_value;
    for (const Json &section : sectionRegistry.sections)
        sections_by_value.emplace(section["value"].int_value(), section);
    for (int value = 0; value < sectionRegistry.count; value++) {
        const auto found = sections_by_value.find(value);
        require_product_registry(found != sections_by_value.end(),
                                 "map-section metadata lacks value " + std::to_string(value));
        const Json &section = found->second;
        const string region = json_to_string(section, "region");
        const string kind = json_to_string(section, "kind");
        const string presentation = json_to_string(section, "region_map_type");
        section_metadata_records.push_back(Json::object {
            {"id", json_to_string(section, "id")},
            {"value", value},
            {"region", region},
            {"regionValue", section_region_value(region)},
            {"kind", kind},
            {"kindValue", section_kind_value(kind)},
            {"regionMapType", presentation},
            {"regionMapTypeValue", region_map_type_value(presentation)},
        });
    }
    map<string, string> layout_symbols_by_id;
    map<string, string> layout_formats_by_id;
    for (const Json &layout : layouts_data["layouts"].array_items()) {
        layout_symbols_by_id.emplace(json_to_string(layout, "id"), json_to_string(layout, "name"));
        layout_formats_by_id.emplace(json_to_string(layout, "id"), json_to_string(layout, "format"));
    }
    int grouped_map_count = 0;
    int active_johto_map_count = 0;
    int nonempty_group_count = 0;
    int reviewed_empty_group_count = 0;

    int group_number = 0;
    for (const Json &group_value : groups_data["group_order"].array_items()) {
        const string group_name = json_to_string(group_value);
        int map_number = 0;
        int included_count = 0;
        for (const Json &map_value : groups_data[group_name].array_items()) {
            const string map_name = json_to_string(map_value);
            auto found = maps_by_name.find(map_name);
            require_product_registry(found != maps_by_name.end(),
                                     "group '" + group_name + "' names missing map '" + map_name + "'");
            const Json &map_data = found->second;
            const string region = json_to_string(map_data, "region");
            if (!policy.IncludesRegion(region)) {
                map_number++;
                continue;
            }

            require_product_registry(grouped_names.insert(map_name).second,
                                     "map '" + map_name + "' appears in more than one group");
            const string scripts_owner = map_data["shared_scripts_map"] == Json()
                ? map_name : json_to_string(map_data, "shared_scripts_map");
            const string events_owner = map_data["shared_events_map"] == Json()
                ? map_name : json_to_string(map_data, "shared_events_map");
            const string layout_id = json_to_string(map_data, "layout");
            auto layout_symbol = layout_symbols_by_id.find(layout_id);
            require_product_registry(layout_symbol != layout_symbols_by_id.end(),
                                     "map '" + map_name + "' names missing layout '" + layout_id + "'");
            if (layout_formats_by_id.at(layout_id) == "johto")
                active_johto_map_count++;
            const bool has_connections = map_data["connections"] != Json()
                && !map_data["connections"].array_items().empty()
                && json_to_string(map_data, "connections_no_include", true) != "TRUE";
            const string sectionId = json_to_string(map_data, "region_map_section");
            const auto sectionValue = sectionValues.find(sectionId);
            require_product_registry(sectionValue != sectionValues.end(),
                                     "map '" + map_name + "' names unknown map section '" + sectionId + "'");
            required_symbols.insert(map_name);
            required_symbols.insert(layout_symbol->second);
            required_symbols.insert(scripts_owner + "_MapScripts");
            required_symbols.insert(events_owner + "_MapEvents");
            if (has_connections)
                required_symbols.insert(map_name + "_MapConnections");

            map_records.push_back(Json::object {
                {"name", map_name},
                {"id", json_to_string(map_data, "id")},
                {"group", group_number},
                {"number", map_number},
                {"region", region},
                {"regionMapSection", sectionId},
                {"regionMapSectionValue", sectionValue->second},
                {"battleType", map_battle_scene_value(json_to_string(map_data, "battle_scene"))},
                {"layoutId", layout_id},
                {"mapLayout", layout_symbol->second},
                {"mapEvents", events_owner + "_MapEvents"},
                {"mapScripts", scripts_owner + "_MapScripts"},
                {"mapConnections", has_connections ? Json(map_name + "_MapConnections") : Json()},
            });
            grouped_map_count++;
            included_count++;
            map_number++;
        }
        if (included_count > 0) {
            nonempty_group_count++;
            required_symbols.insert(group_name);
        } else if (group_number == 96 && group_name == "gMapGroup_IndoorSSAqua"
                   && groups_data[group_name].array_items().empty()) {
            reviewed_empty_group_count++;
            required_symbols.insert(group_name);
        }
        group_records.push_back(Json::object {
            {"name", group_name},
            {"number", group_number},
            {"mapCount", included_count},
        });
        group_number++;
    }
    required_symbols.insert(json_to_string(groups_data, "groups_table_label", true).empty()
                                ? "gMapGroups" : json_to_string(groups_data, "groups_table_label"));

    int included_layout_count = 0;
    int active_johto_layout_count = 0;
    int layout_number = 1;
    set<string> referenced_layout_ids;
    for (const auto &[name, map_data] : maps_by_name)
        referenced_layout_ids.insert(json_to_string(map_data, "layout"));
    set<string> orphan_johto_layout_ids;
    for (const Json &layout : layouts_data["layouts"].array_items()) {
        const string format = json_to_string(layout, "format");
        GetLayoutFormatSpec(format);
        if (policy.IncludesLayout(format)) {
            const string layout_name = json_to_string(layout, "name");
            const string layout_id = json_to_string(layout, "id");
            if (format == "johto" && !referenced_layout_ids.count(layout_id))
                orphan_johto_layout_ids.insert(layout_id);
            const string primary_tileset = json_to_string(layout, "primary_tileset");
            const string secondary_tileset = json_to_string(layout, "secondary_tileset");
            layout_records.push_back(Json::object {
                {"id", layout_id},
                {"name", layout_name},
                {"number", layout_number},
                {"format", format},
                {"width", layout["width"].int_value()},
                {"height", layout["height"].int_value()},
                {"border", layout_name + "_Border"},
                {"map", layout_name + "_Blockdata"},
                {"primaryTileset", primary_tileset},
                {"secondaryTileset", secondary_tileset == "0" || secondary_tileset == "NULL"
                                         ? Json() : Json(secondary_tileset)},
                {"layoutFormatValue", GetLayoutFormatSpec(format).encodedValue},
                {"borderWidth", format == "frlg" ? layout["border_width"].int_value() : 0},
                {"borderHeight", format == "frlg" ? layout["border_height"].int_value() : 0},
            });
            required_symbols.insert(layout_name);
            required_symbols.insert(layout_name + "_Border");
            required_symbols.insert(layout_name + "_Blockdata");
            required_symbols.insert(primary_tileset);
            used_tilesets.insert(primary_tileset);
            if (secondary_tileset != "0" && secondary_tileset != "NULL")
                required_symbols.insert(secondary_tileset);
            if (secondary_tileset != "0" && secondary_tileset != "NULL")
                used_tilesets.insert(secondary_tileset);
            included_layout_count++;
            if (format == "johto")
                active_johto_layout_count++;
        }
        layout_number++;
    }
    required_symbols.insert(json_to_string(layouts_data, "layouts_table_label"));

    const map<string, TilesetDependency> tileset_dependencies = parse_tileset_dependencies();
    for (const string &tileset_name : used_tilesets) {
        auto found = tileset_dependencies.find(tileset_name);
        require_product_registry(found != tileset_dependencies.end(),
                                 "layout references undeclared tileset '" + tileset_name + "'");
        const TilesetDependency &dependency = found->second;
        const bool null_callback = dependency.callback == "NULL" || dependency.callback == "0";
        tileset_records.push_back(Json::object {
            {"name", tileset_name},
            {"tiles", dependency.tiles},
            {"palettes", dependency.palettes},
            {"metatiles", dependency.metatiles},
            {"metatileAttributes", dependency.metatileAttributes},
            {"attributeFormat", dependency.attributeFormat},
            {"callback", null_callback ? Json() : Json(dependency.callback)},
            {"allowNullCallback", null_callback},
        });
        required_symbols.insert(dependency.tiles);
        required_symbols.insert(dependency.palettes);
        required_symbols.insert(dependency.metatiles);
        required_symbols.insert(dependency.metatileAttributes);
        if (!null_callback)
            required_symbols.insert(dependency.callback);
    }

    const Json exclusions_data = read_json_file("tools/mapjson/product_exclusions.json",
                                                "checking reviewed product exclusions");
    set<string> excluded_names;
    for (const Json &exclusion : exclusions_data["exclusions"].array_items()) {
        const string name = json_to_string(exclusion, "name");
        auto found = maps_by_name.find(name);
        require_product_registry(found != maps_by_name.end(),
                                 "reviewed exclusion names missing map '" + name + "'");
        require_product_registry(grouped_names.find(name) == grouped_names.end(),
                                 "reviewed exclusion '" + name + "' is also grouped");
        require_product_registry(json_to_string(found->second, "id") == json_to_string(exclusion, "id"),
                                 "reviewed exclusion '" + name + "' has a changed id");
        require_product_registry(json_to_string(found->second, "region") == json_to_string(exclusion, "region"),
                                 "reviewed exclusion '" + name + "' has a changed region");
        require_product_registry(excluded_names.insert(name).second,
                                 "duplicate reviewed exclusion '" + name + "'");
        exclusion_records.push_back(exclusion);
    }

    if (policy.IsProduct()) {
        set<string> ungrouped_names;
        for (const string &name : reviewed_names) {
            if (grouped_names.find(name) == grouped_names.end())
                ungrouped_names.insert(name);
        }
        const int expected_grouped_maps = 935 + active_johto_map_count;
        require_product_registry(nonempty_group_count + reviewed_empty_group_count == group_number,
                                 "one or more group pointer slots would be null");
        require_product_registry(grouped_map_count == expected_grouped_maps,
                                 "grouped map count disagrees with the active Johto closure");
        require_product_registry(static_cast<int>(map_filepaths.size()) == grouped_map_count + 4,
                                 "reviewed map count disagrees with grouped maps plus exclusions");
        require_product_registry(region_counts["REGION_HOENN"] == 518, "expected 518 Hoenn maps");
        require_product_registry(region_counts["REGION_KANTO"] == 422, "expected 422 Kanto/Sevii maps");
        require_product_registry(region_counts["REGION_JOHTO"] == 253, "expected 253 Johto maps");
        require_product_registry(active_johto_map_count > 0 && active_johto_layout_count > 0,
                                 "expected an active Johto-format closure");
        require_product_registry(orphan_johto_layout_ids == set<string> {
                                     "LAYOUT_TIN_TOWER_ROOF_NIGHT",
                                 },
                                 "unexpected active mapless Johto layout closure");
        require_product_registry(included_layout_count == 785 + active_johto_layout_count,
                                 "layout count disagrees with the active Johto closure");
        require_product_registry(ungrouped_names == excluded_names,
                                 "ungrouped map directories differ from the explicit exclusion list");
    }

    required_symbols.insert("gMapGroupsEnd");
    required_symbols.insert("gMapLayoutsEnd");
    required_symbols.insert("gMapSectionMetadata");
    required_symbols.insert("gMapSectionToSavedLocation");
    required_symbols.insert("gMapSectionToMetLocation");
    required_symbols.insert("gSavedLocationToMapSection");
    required_symbols.insert("gMetLocationToMapSection");
    required_symbols.insert("gMapSectionRegistry");
    required_symbols.insert("gSurfEdgeExits");
    required_symbols.insert("gSurfEdgeExitCount");
    required_symbols.insert("gSurfEdgeRouteProfiles");
    required_symbols.insert("gSurfEdgeRouteProfileCount");

    Json::array surf_edge_exit_records;
    for (const SurfEdgeExitRecord &exit : surfEdgeExits) {
        surf_edge_exit_records.push_back(Json::object {
            {"sourceName", exit.sourceName},
            {"sourceId", exit.sourceId},
            {"sourceMapValue", exit.sourceNumber | (exit.sourceGroup << 8)},
            {"sourceGroup", exit.sourceGroup},
            {"sourceNumber", exit.sourceNumber},
            {"targetName", exit.targetName},
            {"targetId", exit.targetId},
            {"targetMapValue", exit.targetNumber | (exit.targetGroup << 8)},
            {"targetGroup", exit.targetGroup},
            {"targetNumber", exit.targetNumber},
            {"exitEdge", exit.exitEdge},
            {"exitEdgeValue", exit.exitEdgeValue},
            {"targetFacing", exit.targetFacing},
            {"targetFacingValue", exit.targetFacingValue},
            {"targetX", exit.targetX},
            {"targetY", exit.targetY},
        });
    }

    Json::array surf_edge_route_profile_records;
    for (const SurfEdgeExitRecord &exit : surfEdgeExits) {
        if (exit.routeProfileValue != 0) {
            surf_edge_route_profile_records.push_back(Json::object {
                {"sourceName", exit.sourceName},
                {"sourceId", exit.sourceId},
                {"sourceMapValue", exit.sourceNumber | (exit.sourceGroup << 8)},
                {"sourceGroup", exit.sourceGroup},
                {"sourceNumber", exit.sourceNumber},
                {"exitEdge", exit.exitEdge},
                {"exitEdgeValue", exit.exitEdgeValue},
                {"profile", exit.routeProfile},
                {"profileValue", exit.routeProfileValue},
            });
        }
    }

    Json::array symbol_records;
    for (const string &symbol : required_symbols)
        symbol_records.push_back(Json::object {{"name", symbol}, {"kind", "rom"}});

    const Json manifest = Json::object {
        {"schemaVersion", 4},
        {"product", Json::object {
            {"gameVersion", "EMERALD"},
            {"mapVersion", MapBuildModeName(policy.mode)},
            {"allRegions", policy.IsProduct() ? 1 : 0},
            {"fileName", policy.IsProduct() ? "pokemon-openworld" : "generator-fixture"},
        }},
        {"counts", Json::object {
            {"groups", nonempty_group_count + reviewed_empty_group_count},
            {"groupedMaps", grouped_map_count},
            {"reviewedMaps", static_cast<int>(map_filepaths.size())},
            {"layouts", included_layout_count},
            {"edgeExits", static_cast<int>(surfEdgeExits.size())},
            {"edgeRouteProfiles", static_cast<int>(surf_edge_route_profile_records.size())},
            {"regions", Json::object {
                {"REGION_HOENN", region_counts["REGION_HOENN"]},
                {"REGION_KANTO", region_counts["REGION_KANTO"]},
                {"REGION_JOHTO", region_counts["REGION_JOHTO"]},
            }},
        }},
        {"abis", Json::object {
            {"mapHeader", Json::object {
                {"size", 32},
                {"alignment", 4},
                {"regionMapSectionIdOffset", 20},
                {"battleTypeOffset", 28},
                {"paddingOffset", 29},
                {"paddingSize", 3},
            }},
            {"mapLayout", Json::object {
                {"size", 28}, {"alignment", 4}, {"widthOffset", 0},
                {"heightOffset", 4}, {"borderOffset", 8}, {"mapOffset", 12},
                {"primaryTilesetOffset", 16}, {"secondaryTilesetOffset", 20},
                {"formatOffset", 24}, {"borderWidthOffset", 25},
                {"borderHeightOffset", 26}, {"paddingOffset", 27},
            }},
            {"tileset", Json::object {
                {"size", 24}, {"alignment", 4}, {"flagsOffset", 1},
                {"tilesOffset", 4}, {"palettesOffset", 8}, {"metatilesOffset", 12},
                {"metatileAttributesOffset", 16}, {"callbackOffset", 20},
            }},
            {"mapSectionRegistry", Json::object {
                {"size", 24}, {"alignment", 4}, {"metadataOffset", 0},
                {"sectionToSavedLocationOffset", 4}, {"sectionToMetLocationOffset", 8},
                {"savedLocationToSectionOffset", 12}, {"metLocationToSectionOffset", 16},
                {"sectionCountOffset", 20},
            }},
            {"surfEdgeExit", Json::object {
                {"size", 10}, {"alignment", 2}, {"sourceMapOffset", 0},
                {"targetMapOffset", 2}, {"targetXOffset", 4},
                {"targetYOffset", 6}, {"exitEdgeOffset", 8},
                {"targetFacingOffset", 9},
            }},
            {"surfEdgeRouteProfile", Json::object {
                {"size", 4}, {"alignment", 2}, {"sourceMapOffset", 0},
                {"exitEdgeOffset", 2}, {"profileOffset", 3},
            }},
        }},
        {"countSentinels", Json::object {
            {"groups", Json::object {{"start", "gMapGroups"}, {"end", "gMapGroupsEnd"},
                                      {"count", group_number}, {"stride", 4}}},
            {"layouts", Json::object {{"start", json_to_string(layouts_data, "layouts_table_label")},
                                       {"end", "gMapLayoutsEnd"}, {"count", included_layout_count}, {"stride", 4}}},
            {"mapSections", Json::object {{"registry", "gMapSectionRegistry"},
                                           {"count", sectionRegistry.count}}},
            {"edgeExits", Json::object {{"registry", "gSurfEdgeExits"},
                                         {"countSymbol", "gSurfEdgeExitCount"},
                                         {"count", static_cast<int>(surfEdgeExits.size())},
                                         {"stride", 10}}},
            {"edgeRouteProfiles", Json::object {{"registry", "gSurfEdgeRouteProfiles"},
                                                  {"countSymbol", "gSurfEdgeRouteProfileCount"},
                                                  {"count", static_cast<int>(surf_edge_route_profile_records.size())},
                                                  {"stride", 4}}},
        }},
        {"codecs", Json::object {
            {"sectionToSavedLocation", sectionRegistry.sectionToSaved},
            {"sectionToMetLocation", sectionRegistry.sectionToMet},
            {"savedLocationToSection", sectionRegistry.savedToSection},
            {"metLocationToSection", sectionRegistry.metToSection},
        }},
        {"mapSectionMetadata", section_metadata_records},
        {"edgeExits", surf_edge_exit_records},
        {"edgeRouteProfiles", surf_edge_route_profile_records},
        {"exclusions", exclusion_records},
        {"groups", group_records},
        {"maps", map_records},
        {"layouts", layout_records},
        {"tilesets", tileset_records},
        {"symbols", symbol_records},
    };
    write_text_file((staging / "integrity-manifest.json").string(), manifest.dump() + "\n");
}

static std::filesystem::path reserve_generation_staging(const std::filesystem::path &destination)
{
    const std::filesystem::path parent = destination.parent_path();
    std::filesystem::create_directories(parent);
    const auto nonce = std::chrono::steady_clock::now().time_since_epoch().count();

    for (unsigned int attempt = 0; attempt < 1000; attempt++) {
        std::filesystem::path staging = parent / (".staging-" + std::to_string(nonce) + "-" + std::to_string(attempt));
        std::error_code ec;
        if (std::filesystem::create_directory(staging, ec))
            return staging;
        if (ec && ec != std::errc::file_exists)
            FATAL_ERROR("Failed to reserve generation staging tree '%s': %s\n", staging.string().c_str(), ec.message().c_str());
    }
    FATAL_ERROR("Failed to reserve a unique generation staging tree below '%s'.\n", parent.string().c_str());
}

#ifndef _WIN32
class GenerationLock
{
public:
    explicit GenerationLock(const std::filesystem::path &parent)
    {
        const std::filesystem::path lock_path = parent / ".generation.lock";
        descriptor = open(lock_path.c_str(), O_CREAT | O_RDWR, 0666);
        if (descriptor < 0 || flock(descriptor, LOCK_EX) != 0)
            FATAL_ERROR("Failed to lock generation directory '%s'.\n", parent.string().c_str());
    }

    ~GenerationLock()
    {
        flock(descriptor, LOCK_UN);
        close(descriptor);
    }

private:
    int descriptor = -1;
};
#else
class GenerationLock
{
public:
    explicit GenerationLock(const std::filesystem::path &parent)
    {
        const std::filesystem::path lock_path = parent / ".generation.lock";
        for (;;) {
            handle = CreateFileW(lock_path.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr,
                                 OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
            if (handle != INVALID_HANDLE_VALUE)
                return;
            if (GetLastError() != ERROR_SHARING_VIOLATION)
                FATAL_ERROR("Failed to lock generation directory '%s'.\n", parent.string().c_str());
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
    }

    ~GenerationLock()
    {
        CloseHandle(handle);
    }

private:
    HANDLE handle = INVALID_HANDLE_VALUE;
};
#endif

static void remove_generation_work_trees(const std::filesystem::path &parent)
{
    set<string> referenced_generations;
    std::error_code canonical_error;
    const std::filesystem::path canonical_parent = std::filesystem::canonical(parent, canonical_error);
    if (canonical_error)
        FATAL_ERROR("Failed to resolve generation directory '%s': %s\n",
                    parent.string().c_str(), canonical_error.message().c_str());
    std::error_code iterator_error;
    for (std::filesystem::directory_iterator it(parent, iterator_error), end;
         !iterator_error && it != end; it.increment(iterator_error)) {
        std::error_code status_error;
        if (!std::filesystem::is_symlink(it->symlink_status(status_error)) || status_error)
            continue;
        const std::filesystem::path target = std::filesystem::read_symlink(it->path(), status_error);
        if (status_error)
            continue;
        const std::filesystem::path resolved_target = std::filesystem::canonical(parent / target, status_error);
        if (status_error)
            continue;
        const std::filesystem::path relative_target = resolved_target.lexically_relative(canonical_parent);
        if (relative_target.empty() || relative_target.is_absolute())
            continue;
        const auto first_component = relative_target.begin();
        if (first_component == relative_target.end() || *first_component == "..")
            continue;
        const string generation_name = first_component->string();
        if (generation_name.rfind(".generation-", 0) == 0)
            referenced_generations.insert(generation_name);
    }
    if (iterator_error)
        FATAL_ERROR("Failed to inspect generation pointers below '%s': %s\n",
                    parent.string().c_str(), iterator_error.message().c_str());

    iterator_error.clear();
    for (std::filesystem::directory_iterator it(parent, iterator_error), end;
         !iterator_error && it != end; it.increment(iterator_error)) {
        const string name = it->path().filename().string();
        if (name.rfind(".staging-", 0) != 0 && name.rfind(".generation-", 0) != 0)
            continue;
        if (referenced_generations.count(name))
            continue;
        std::error_code remove_error;
        std::filesystem::remove_all(it->path(), remove_error);
        if (remove_error)
            FATAL_ERROR("Failed to remove stale generation tree '%s': %s\n",
                        it->path().string().c_str(), remove_error.message().c_str());
    }
    if (iterator_error)
        FATAL_ERROR("Failed to inspect generation directory '%s': %s\n",
                    parent.string().c_str(), iterator_error.message().c_str());
}

static void promote_generation_tree(const std::filesystem::path &staging,
                                    const std::filesystem::path &destination)
{
    const string token = staging.filename().string().substr(string(".staging-").size());
    const std::filesystem::path published = staging.parent_path() / (".generation-" + token);
    const std::filesystem::path next_link = staging.parent_path() / (".current-" + token);
    std::error_code ec;

    std::filesystem::rename(staging, published, ec);
    if (ec)
        FATAL_ERROR("Failed to finalize generation tree '%s': %s\n", published.string().c_str(), ec.message().c_str());

    std::filesystem::create_directory_symlink(published.filename(), next_link, ec);
    if (ec)
        FATAL_ERROR("Failed to create generation pointer '%s': %s\n", next_link.string().c_str(), ec.message().c_str());

    const std::filesystem::file_status destination_status = std::filesystem::symlink_status(destination, ec);
    if (ec && ec != std::errc::no_such_file_or_directory)
        FATAL_ERROR("Failed to inspect generation pointer '%s': %s\n", destination.string().c_str(), ec.message().c_str());
    if (destination_status.type() != std::filesystem::file_type::not_found
     && destination_status.type() != std::filesystem::file_type::symlink) {
        std::filesystem::remove(next_link, ec);
        FATAL_ERROR("Generation destination '%s' must be absent or a symbolic link; remove the legacy generated directory first.\n",
                    destination.string().c_str());
    }

    // POSIX rename atomically replaces the old symlink. Readers therefore see
    // either the complete prior tree or the complete new tree, never a gap.
    std::filesystem::rename(next_link, destination, ec);
    if (ec)
        FATAL_ERROR("Failed to publish generation pointer '%s': %s\n", destination.string().c_str(), ec.message().c_str());

    remove_generation_work_trees(staging.parent_path());
}

static map<string, int> allocate_product_hidden_item_flags(const MapBuildPolicy &policy,
                                                           const vector<string> &map_filepaths)
{
    map<string, int> allocations;
    if (!policy.IsProduct())
        return allocations;

    set<string> reviewed_flags;
    for (const string &filepath : map_filepaths) {
        const Json map_data = read_json_file(filepath, "allocating all-regions hidden-item flags");
        if (json_to_string(map_data, "region") != "REGION_KANTO")
            continue;
        for (const Json &event : map_data["bg_events"].array_items()) {
            if (json_to_string(event, "type", true) == "hidden_item")
                reviewed_flags.insert(json_to_string(event, "flag"));
        }
    }

    const Json policy_data = read_json_file("tools/mapjson/product_hidden_item_flags.json",
                                            "loading all-regions hidden-item flag pools");
    vector<int> available;
    for (const Json &pool : policy_data["unusedFlagPools"].array_items()) {
        const int first = pool["first"].int_value();
        const int last = pool["last"].int_value();
        require_product_registry(first >= 0x1F4 && last >= first && last < 0x8FE,
                                 "invalid hidden-item flag pool");
        for (int value = first; value <= last; value++)
            available.push_back(value);
    }
    require_product_registry(reviewed_flags.size() == 183,
                             "expected 183 Kanto/Sevii hidden-item flags, got "
                                 + std::to_string(reviewed_flags.size()));
    require_product_registry(available.size() >= reviewed_flags.size(),
                             "reviewed hidden-item flag pools are too small");

    size_t index = 0;
    for (const string &flag : reviewed_flags)
        allocations.emplace(flag, available[index++]);
    return allocations;
}

static bool is_stable_identifier(const string &value)
{
    static const std::regex identifier("^[A-Za-z_][A-Za-z0-9_]*$");
    return std::regex_match(value, identifier);
}

static void require_array_field(const Json &owner, const string &owner_name, const string &field)
{
    require_product_registry(owner[field].type() == Json::Type::ARRAY,
                             "map '" + owner_name + "' lacks " + field + " event registry");
}

static bool script_registry_defines(const std::filesystem::path &path, const string &owner)
{
    const std::regex declaration("^[ \\t]*" + owner
                                 + "_MapScripts::[ \\t]*(?:(?:@|//).*)?$");
    std::istringstream lines(read_text_file(path.string()));
    string line;
    while (std::getline(lines, line)) {
        if (!line.empty() && line.back() == '\r')
            line.pop_back();
        if (std::regex_match(line, declaration))
            return true;
    }
    return false;
}

static bool global_script_registry_defines(const string &owner)
{
    std::error_code error;
    for (std::filesystem::recursive_directory_iterator it("data/scripts", error), end;
         !error && it != end; it.increment(error)) {
        if (it->is_regular_file() && it->path().extension() == ".inc"
         && script_registry_defines(it->path(), owner))
            return true;
    }
    return false;
}

static void validate_checkpoint_registry(const Json &checkpoints_data,
                                         const Json &published_bindings_data,
                                         const Json &layouts_data,
                                         const map<string, Json> &maps_by_name,
                                         const map<string, string> &map_names_by_id,
                                         const set<string> &grouped_names)
{
    require_product_registry(checkpoints_data["heal_locations"].type() == Json::Type::ARRAY,
                             "checkpoint registry lacks heal_locations array");
    require_product_registry(published_bindings_data["entries"].type() == Json::Type::ARRAY,
                             "published allocation ledger lacks entries array");

    map<string, std::pair<int, int>> layout_dimensions;
    for (const Json &layout : layouts_data["layouts"].array_items()) {
        layout_dimensions.emplace(json_to_string(layout, "id"),
                                  std::make_pair(layout["width"].int_value(),
                                                 layout["height"].int_value()));
    }

    map<string, int> published;
    for (const Json &binding : published_bindings_data["entries"].array_items()) {
        if (json_to_string(binding, "domain", true) != "checkpoints"
         || json_to_string(binding, "source", true) != "heal-locations")
            continue;
        const string symbol = json_to_string(binding, "symbol");
        require_product_registry(binding["value"].type() == Json::Type::NUMBER,
                                 "checkpoint binding '" + symbol + "' lacks numeric value");
        require_product_registry(published.emplace(symbol, binding["value"].int_value()).second,
                                 "duplicate published checkpoint binding '" + symbol + "'");
    }
    require_product_registry(published.count("HEAL_LOCATION_NONE")
                          && published.at("HEAL_LOCATION_NONE") == 0,
                             "checkpoint binding HEAL_LOCATION_NONE must remain 0");

    const vector<Json> checkpoints = checkpoints_data["heal_locations"].array_items();
    require_product_registry(published.size() == checkpoints.size() + 1,
                             "checkpoint registry is missing a published checkpoint");
    set<string> ids;
    set<string> locations;
    const set<string> allowed_fields = {
        "id", "map", "x", "y", "respawn_map", "respawn_npc",
        "respawn_x", "respawn_y", "recovery_mode",
    };
    for (size_t index = 0; index < checkpoints.size(); index++) {
        const Json &checkpoint = checkpoints[index];
        require_product_registry(checkpoint.type() == Json::Type::OBJECT,
                                 "checkpoint registry contains an empty slot");
        const string id = json_to_string(checkpoint, "id");
        for (const auto &[field, unused] : checkpoint.object_items()) {
            (void)unused;
            require_product_registry(allowed_fields.count(field),
                                     "checkpoint '" + id + "' has unknown field '" + field + "'");
        }
        require_product_registry(is_stable_identifier(id) && ids.insert(id).second,
                                 "checkpoint registry has duplicate or unstable id '" + id + "'");
        const auto binding = published.find(id);
        require_product_registry(binding != published.end(),
                                 "checkpoint '" + id + "' lacks a published binding");
        require_product_registry(binding->second == static_cast<int>(index + 1),
                                 "checkpoint '" + id + "' changed its serialized binding");

        const string map_id = json_to_string(checkpoint, "map");
        const string respawn_map_id = json_to_string(checkpoint, "respawn_map");
        require_product_registry(map_names_by_id.count(map_id),
                                 "checkpoint '" + id + "' names missing map '" + map_id + "'");
        require_product_registry(map_names_by_id.count(respawn_map_id),
                                 "checkpoint '" + id + "' names invalid destination '" + respawn_map_id + "'");
        const string map_name = map_names_by_id.at(map_id);
        const string respawn_map_name = map_names_by_id.at(respawn_map_id);
        require_product_registry(grouped_names.count(map_name),
                                 "checkpoint '" + id + "' source map is outside the product registry");
        require_product_registry(grouped_names.count(respawn_map_name),
                                 "checkpoint '" + id + "' destination is outside the product registry");

        auto coordinate = [&](const string &field) {
            const Json value = checkpoint[field];
            require_product_registry(value.type() == Json::Type::NUMBER
                                  && value.number_value() == value.int_value()
                                  && value.int_value() >= 0
                                  && value.int_value() <= 65535,
                                     "checkpoint '" + id + "' has invalid " + field);
            return value.int_value();
        };
        const int x = coordinate("x");
        const int y = coordinate("y");
        const bool has_respawn_x = checkpoint["respawn_x"].type() != Json::Type::NUL;
        const bool has_respawn_y = checkpoint["respawn_y"].type() != Json::Type::NUL;
        require_product_registry(has_respawn_x == has_respawn_y,
                                 "checkpoint '" + id + "' must author both respawn coordinates or neither");
        const int respawn_x = has_respawn_x ? coordinate("respawn_x") : 7;
        const int respawn_y = has_respawn_y ? coordinate("respawn_y") : 4;

        auto require_in_bounds = [&](const string &owner, int px, int py, const string &kind) {
            const string layout_id = json_to_string(maps_by_name.at(owner), "layout");
            const auto dimensions = layout_dimensions.find(layout_id);
            require_product_registry(dimensions != layout_dimensions.end(),
                                     "checkpoint '" + id + "' map lacks layout dimensions");
            require_product_registry(px < dimensions->second.first && py < dimensions->second.second,
                                     "checkpoint '" + id + "' " + kind + " is outside map bounds");
        };
        require_in_bounds(map_name, x, y, "heal location");
        require_in_bounds(respawn_map_name, respawn_x, respawn_y, "whiteout destination");
        require_product_registry(locations.insert(map_id + ":" + std::to_string(x)
                                                + ":" + std::to_string(y)).second,
                                 "checkpoint '" + id + "' duplicates a heal location");

        const string recovery_mode = json_to_string(checkpoint, "recovery_mode");
        const string healer = json_to_string(checkpoint, "respawn_npc");
        require_product_registry(recovery_mode == "DIRECT" || recovery_mode == "HEALER",
                                 "checkpoint '" + id + "' has invalid recovery mode '"
                                     + recovery_mode + "'");
        if (recovery_mode == "DIRECT") {
            require_product_registry(healer == "LOCALID_NONE",
                                     "direct checkpoint '" + id + "' must not name a healer actor");
            require_product_registry(map_id == respawn_map_id && x == respawn_x && y == respawn_y,
                                     "direct checkpoint '" + id + "' destination must equal its heal location");
            continue;
        }

        require_product_registry(healer != "LOCALID_NONE" && is_stable_identifier(healer),
                                 "healer checkpoint '" + id + "' lacks a healer actor");
        const Json &destination = maps_by_name.at(respawn_map_name);
        const string events_owner = destination["shared_events_map"] == Json()
                                  ? respawn_map_name
                                  : json_to_string(destination, "shared_events_map");
        require_product_registry(maps_by_name.count(events_owner),
                                 "checkpoint '" + id + "' names missing healer event owner");
        int healer_matches = 0;
        for (const Json &object : maps_by_name.at(events_owner)["object_events"].array_items()) {
            if (json_to_string(object, "local_id", true) == healer)
                healer_matches++;
        }
        require_product_registry(healer_matches == 1,
                                 "checkpoint '" + id + "' healer actor '" + healer
                                     + "' is not owned exactly once by destination events");
    }
}

static void validate_product_inputs(const MapBuildPolicy &policy,
                                    const string &groups_filepath,
                                    const string &layouts_filepath,
                                    const vector<string> &map_filepaths,
                                    const string &checkpoints_filepath = "src/data/heal_locations.json",
                                    const string &published_bindings_filepath = "tools/persistence/published_allocations.json")
{
    if (!policy.IsProduct())
        return;

    const Json groups_data = read_json_file(groups_filepath, "validating all-regions groups");
    const Json layouts_data = read_json_file(layouts_filepath, "validating all-regions layouts");
    require_product_registry(groups_data["group_order"].type() == Json::Type::ARRAY,
                             "map groups lack group_order registry");
    require_product_registry(layouts_data["layouts"].type() == Json::Type::ARRAY,
                             "layouts registry lacks layouts array");

    map<string, Json> maps_by_name;
    map<string, string> map_names_by_id;
    map<string, std::filesystem::path> map_paths_by_name;
    for (const string &filepath : map_filepaths) {
        const Json map_data = read_json_file(filepath, "validating all-regions map contract");
        const string name = json_to_string(map_data, "name");
        const string id = json_to_string(map_data, "id");
        require_product_registry(is_stable_identifier(name),
                                 "map '" + name + "' has unstable name identifier");
        require_product_registry(is_stable_identifier(id),
                                 "map '" + name + "' has unstable id '" + id + "'");
        require_product_registry(maps_by_name.emplace(name, map_data).second,
                                 "duplicate map name '" + name + "'");
        require_product_registry(map_names_by_id.emplace(id, name).second,
                                 "duplicate map id '" + id + "'");
        map_paths_by_name.emplace(name, std::filesystem::path(filepath));
    }

    set<string> layout_ids;
    set<string> layout_names;
    map<string, string> included_layouts;
    const map<string, TilesetDependency> tilesets = parse_tileset_dependencies();
    for (const Json &layout : layouts_data["layouts"].array_items()) {
        require_product_registry(layout.type() == Json::Type::OBJECT,
                                 "layouts registry contains an empty layout slot");
        const string id = json_to_string(layout, "id");
        const string name = json_to_string(layout, "name");
        const string format = json_to_string(layout, "format");
        require_product_registry(is_stable_identifier(id) && is_stable_identifier(name),
                                 "layout '" + name + "' has unstable identifiers");
        require_product_registry(layout_ids.insert(id).second,
                                 "duplicate layout id '" + id + "'");
        require_product_registry(layout_names.insert(name).second,
                                 "duplicate layout name '" + name + "'");
        GetLayoutFormatSpec(format);
        if (!policy.IncludesLayout(format))
            continue;
        require_product_registry(layout["width"].type() == Json::Type::NUMBER
                              && layout["width"].int_value() > 0
                              && layout["height"].type() == Json::Type::NUMBER
                              && layout["height"].int_value() > 0,
                                 "layout '" + name + "' has invalid dimensions");
        const string border = json_to_string(layout, "border_filepath");
        const string blockdata = json_to_string(layout, "blockdata_filepath");
        std::error_code error;
        const uintmax_t border_size = std::filesystem::file_size(border, error);
        require_product_registry(!error && border_size > 0,
                                 "layout '" + name + "' lacks border data '" + border + "'");
        error.clear();
        const uintmax_t blockdata_size = std::filesystem::file_size(blockdata, error);
        require_product_registry(!error && blockdata_size > 0,
                                 "layout '" + name + "' lacks blockdata '" + blockdata + "'");
        const string primary = json_to_string(layout, "primary_tileset");
        const string secondary = json_to_string(layout, "secondary_tileset");
        require_product_registry(tilesets.count(primary),
                                 "layout '" + name + "' lacks primary tileset '" + primary + "'");
        require_product_registry(secondary == "0" || secondary == "NULL" || tilesets.count(secondary),
                                 "layout '" + name + "' lacks secondary tileset '" + secondary + "'");
        require_product_registry(included_layouts.emplace(id, name).second,
                                 "layout id '" + id + "' is not stable");
    }

    set<string> grouped_names;
    int group_number = 0;
    for (const Json &group_value : groups_data["group_order"].array_items()) {
        const string group_name = json_to_string(group_value);
        require_product_registry(is_stable_identifier(group_name),
                                 "group '" + group_name + "' has an unstable identifier");
        require_product_registry(group_number <= 127,
                                 "group '" + group_name + "' exceeds signed WarpData range");
        require_product_registry(groups_data[group_name].type() == Json::Type::ARRAY,
                                 "group '" + group_name + "' lacks its map registry");
        int map_number = 0;
        for (const Json &map_value : groups_data[group_name].array_items()) {
            const string map_name = json_to_string(map_value);
            require_product_registry(map_number <= 127,
                                     "map '" + map_name + "' exceeds signed WarpData range in group '"
                                         + group_name + "'");
            require_product_registry(maps_by_name.count(map_name),
                                     "group '" + group_name + "' names missing map '" + map_name + "'");
            require_product_registry(grouped_names.insert(map_name).second,
                                     "map '" + map_name + "' appears in more than one group");
            map_number++;
        }
        group_number++;
    }

    for (const auto &[map_name, map_data] : maps_by_name) {
        if (!policy.IncludesRegion(json_to_string(map_data, "region")))
            continue;
        if (!grouped_names.count(map_name))
            continue; // Explicit reviewed exclusions are checked by the manifest contract.
        const string layout_id = json_to_string(map_data, "layout");
        require_product_registry(included_layouts.count(layout_id),
                                 "map '" + map_name + "' names missing product layout '" + layout_id + "'");
        const string section = json_to_string(map_data, "region_map_section");
        require_product_registry(is_stable_identifier(section),
                                 "map '" + map_name + "' lacks stable section metadata");

        const bool shares_events = map_data["shared_events_map"] != Json();
        const bool shares_scripts = map_data["shared_scripts_map"] != Json();
        const string events_owner = shares_events ? json_to_string(map_data, "shared_events_map") : map_name;
        const string scripts_owner = shares_scripts ? json_to_string(map_data, "shared_scripts_map") : map_name;
        require_product_registry(maps_by_name.count(events_owner),
                                 "map '" + map_name + "' names missing events owner '" + events_owner + "'");
        if (maps_by_name.count(scripts_owner)) {
            const std::filesystem::path scripts_path = map_paths_by_name.at(scripts_owner).parent_path() / "scripts.inc";
            require_product_registry(std::filesystem::is_regular_file(scripts_path),
                                     "map '" + map_name + "' lacks scripts registry '" + scripts_path.string() + "'");
            require_product_registry(script_registry_defines(scripts_path, scripts_owner),
                                     "map '" + map_name + "' scripts registry does not define '"
                                         + scripts_owner + "_MapScripts'");
        } else {
            require_product_registry(global_script_registry_defines(scripts_owner),
                                     "map '" + map_name + "' names missing scripts owner '" + scripts_owner + "'");
        }
        const Json &events_data = maps_by_name.at(events_owner);
        require_array_field(events_data, events_owner, "object_events");
        require_array_field(events_data, events_owner, "warp_events");
        require_array_field(events_data, events_owner, "coord_events");
        require_array_field(events_data, events_owner, "bg_events");

        require_product_registry(map_data["connections"].type() == Json::Type::NUL
                              || map_data["connections"].type() == Json::Type::ARRAY
                              || (map_data["connections"].type() == Json::Type::NUMBER
                               && map_data["connections"].int_value() == 0),
                                 "map '" + map_name + "' lacks connections registry");
        for (const Json &connection : map_data["connections"].array_items()) {
            const string destination = json_to_string(connection, "map");
            require_product_registry(map_names_by_id.count(destination),
                                     "map '" + map_name + "' connection names missing map id '" + destination + "'");
        }
        for (const Json &warp : events_data["warp_events"].array_items()) {
            const string destination = json_to_string(warp, "dest_map");
            require_product_registry(destination == "MAP_DYNAMIC" || map_names_by_id.count(destination),
                                     "map '" + events_owner + "' warp names missing map id '" + destination + "'");
        }
    }

    validate_checkpoint_registry(
        read_json_file(checkpoints_filepath, "validating checkpoint registry"),
        read_json_file(published_bindings_filepath, "validating published checkpoint bindings"),
        layouts_data, maps_by_name, map_names_by_id, grouped_names);

    // Map-section validation owns the metadata, compact codecs, reverse maps,
    // stable frozen range, and invalid/reserved sentinels as one contract.
    validate_map_section_registry();
}

static void process_generation_tree(const MapBuildPolicy &policy, const string &groups_filepath,
                                    const string &layouts_filepath, const string &output_root,
                                    vector<string> &map_filepaths)
{
    const Json groupsData = read_json_file(groups_filepath, "validating Surf edge exits");
    const Json layoutsData = read_json_file(layouts_filepath, "validating Surf edge exits");
    const vector<SurfEdgeExitRecord> surfEdgeExits = normalize_surf_edge_exits(
        policy, groupsData, layoutsData, map_filepaths);
    validate_product_inputs(policy, groups_filepath, layouts_filepath, map_filepaths);
    std::filesystem::path destination = strip_trailing_separator(output_root);
    std::filesystem::create_directories(destination.parent_path());
    GenerationLock generation_lock(destination.parent_path());
    remove_generation_work_trees(destination.parent_path());
    std::filesystem::path staging = reserve_generation_staging(destination);

    // GENERATED_ROOT is an aggregate tree: mapjson owns its map products, while
    // persistence and other generators own sibling files below the same root.
    // Seed staging from the currently published aggregate before replacing the
    // map-owned paths. Otherwise a later map promotion can erase siblings that
    // an outer or nested Make has already finished generating.
    std::error_code copy_error;
    if (std::filesystem::exists(destination, copy_error)) {
        const std::filesystem::path published = std::filesystem::canonical(destination, copy_error);
        if (copy_error)
            FATAL_ERROR("Failed to resolve generated aggregate '%s': %s\n",
                        destination.string().c_str(), copy_error.message().c_str());
        std::filesystem::copy(published, staging,
                              std::filesystem::copy_options::recursive
                            | std::filesystem::copy_options::overwrite_existing,
                              copy_error);
        if (copy_error)
            FATAL_ERROR("Failed to seed generation staging tree from '%s': %s\n",
                        destination.string().c_str(), copy_error.message().c_str());
    } else if (copy_error) {
        FATAL_ERROR("Failed to inspect generated aggregate '%s': %s\n",
                    destination.string().c_str(), copy_error.message().c_str());
    }

    // Remove every mapjson-owned path from the aggregate snapshot before
    // regenerating it, so changing product modes cannot retain excluded maps.
    const std::filesystem::path map_owned_paths[] = {
        "data/maps",
        "data/layouts",
        "include/constants/map_groups.h",
        "include/constants/layouts.h",
        "include/constants/map_event_ids.h",
        "include/generated/map_section_metadata.h",
        "src/data/map_group_count.h",
        "src/data/debug_map_names.h",
        "src/data/map_section_metadata.inc.c",
        "src/data/surf_edge_exits.inc.c",
        "integrity-manifest.json",
        ".map-build-policy",
    };
    for (const std::filesystem::path &relative : map_owned_paths) {
        std::filesystem::remove_all(staging / relative, copy_error);
        if (copy_error)
            FATAL_ERROR("Failed to clear map-owned staging path '%s': %s\n",
                        relative.string().c_str(), copy_error.message().c_str());
    }

    const std::filesystem::path maps_out = staging / "data" / "maps";
    const std::filesystem::path layouts_out = staging / "data" / "layouts";
    const std::filesystem::path constants_out = staging / "include" / "constants";
    std::filesystem::create_directories(maps_out);
    std::filesystem::create_directories(layouts_out);
    std::filesystem::create_directories(constants_out);

    const map<string, int> hidden_item_flags = allocate_product_hidden_item_flags(policy, map_filepaths);

    process_groups(groups_filepath, map_filepaths, maps_out.string(), constants_out.string(), policy,
                   (destination / "data" / "maps").string());
    process_layouts(layouts_filepath, layouts_out.string(), constants_out.string(), policy);
    process_event_constants(map_filepaths, (constants_out / "map_event_ids.h").string());
    write_map_section_metadata(staging);
    write_surf_edge_exit_registry(staging, surfEdgeExits);
    write_integrity_manifest(staging, policy, groups_filepath, layouts_filepath, map_filepaths,
                             surfEdgeExits);

    vector<string> existing_maps = included_map_ids(map_filepaths, policy);
    for (const string &filepath : map_filepaths) {
        string err;
        Json map_data = Json::parse(read_text_file(filepath), err);
        if (map_data == Json())
            FATAL_ERROR("Failed to read '%s' while generating map files: %s\n", filepath.c_str(), err.c_str());
        std::filesystem::path map_out = maps_out / json_to_string(map_data, "name");
        std::filesystem::create_directories(map_out);
        process_map(filepath, layouts_filepath, map_out.string(), policy, existing_maps, hidden_item_flags);
    }

    write_text_file((staging / ".map-build-policy").string(),
                    string(MapBuildModeName(policy.mode)) + "\n");
    promote_generation_tree(staging, destination);
}

int main(int argc, char *argv[]) {
    if (argc < 3)
        FATAL_ERROR("USAGE: mapjson <mode> <game-version> [options]\n");

    MapBuildPolicy policy = ParseBuildPolicy(argv[2]);

    char *mode_arg = argv[1];
    string mode(mode_arg);
    if (mode == "map") {
        if (argc != 6)
            FATAL_ERROR("USAGE: mapjson map <game-version> <map_file> <layouts_file> <output_dir>\n");

        infer_separator(argv[3]);
        string filepath(argv[3]);
        string layouts_filepath(argv[4]);
        string output_dir(argv[5]);

        process_map(filepath, layouts_filepath, output_dir, policy,
                    sibling_map_ids(filepath, policy));
    }
    else if (mode == "groups") {
        if (argc < 6)
            FATAL_ERROR("USAGE: mapjson groups <game-version> <groups_file> <map_file> [additional_map_files] <output_asm_dir> <output_c_dir>\n");

        infer_separator(argv[3]);
        string filepath(argv[3]);

        vector<string> map_filepaths;
        const int firstMapFileArg = 4;
        const int lastMapFileArg = argc - 3;
        for (int i = firstMapFileArg; i <= lastMapFileArg; i++) {
            map_filepaths.push_back(argv[i]);
        }

        string output_asm(argv[argc - 2]);
        string output_c(argv[argc - 1]);

        process_groups(filepath, map_filepaths, output_asm, output_c, policy);
    }
    else if (mode == "layouts") {
        if (argc != 6)
            FATAL_ERROR("USAGE: mapjson layouts <game-version> <layouts_file> <output_asm_dir> <output_c_dir>\n");

        infer_separator(argv[3]);
        string filepath(argv[3]);
        string output_asm(argv[4]);
        string output_c(argv[5]);

        process_layouts(filepath, output_asm, output_c, policy);
    }
    else if (mode == "event_constants") {
        if (argc < 5)
            FATAL_ERROR("USAGE: mapjson event_constants <game-version> <map_file> [additional_map_files] <output_ids_file>");

        infer_separator(argv[3]);

        vector<string> filepaths;
        const int firstMapFileArg = 3;
        const int lastMapFileArg = argc - 2;
        for (int i = firstMapFileArg; i <= lastMapFileArg; i++) {
            filepaths.push_back(argv[i]);
        }
        string output_ids_file(argv[argc - 1]);

        process_event_constants(filepaths, output_ids_file);
    }
    else if (mode == "policy") {
        if (argc != 3)
            FATAL_ERROR("USAGE: mapjson policy <build-mode>\n");
        cout << "mode=" << MapBuildModeName(policy.mode) << "\n"
             << "dialect=" << DataDialectName(policy.defaultDialect) << "\n"
             << "hoenn=" << policy.IncludesRegion("REGION_HOENN") << "\n"
             << "kanto=" << policy.IncludesRegion("REGION_KANTO") << "\n"
             << "johto=" << policy.IncludesRegion("REGION_JOHTO") << "\n"
             << "emerald_layout=" << policy.IncludesLayout("emerald") << "\n"
             << "frlg_layout=" << policy.IncludesLayout("frlg") << "\n"
             << "johto_layout=" << policy.IncludesLayout("johto") << "\n"
             << "ruby_layout=" << policy.IncludesLayout("ruby") << "\n"
             << "product=" << policy.IsProduct() << "\n";
    }
    else if (mode == "sections") {
        if (argc != 5)
            FATAL_ERROR("USAGE: mapjson sections <build-mode> <registry> <compatibility>\n");
        const MapSectionRegistry registry = validate_map_section_registry(argv[3], argv[4]);
        cout << "count=" << registry.count << "\n";
    }
    else if (mode == "script_registry") {
        if (argc != 5)
            FATAL_ERROR("USAGE: mapjson script_registry <build-mode> <owner> <file>\n");
        if (!script_registry_defines(argv[4], argv[3]))
            FATAL_ERROR("Script registry '%s' does not define '%s_MapScripts'.\n", argv[4], argv[3]);
        cout << "owner=" << argv[3] << "\n";
    }
    else if (mode == "checkpoints") {
        if (argc < 8)
            FATAL_ERROR("USAGE: mapjson checkpoints <build-mode> <groups_file> <layouts_file> <checkpoint_registry> <published_bindings> <map_file> [additional_map_files]\n");
        infer_separator(argv[3]);
        vector<string> map_filepaths;
        for (int i = 7; i < argc; i++)
            map_filepaths.push_back(argv[i]);
        validate_product_inputs(policy, argv[3], argv[4], map_filepaths, argv[5], argv[6]);
        cout << "checkpoints=valid\n";
    }
    else if (mode == "edge_exits") {
        if (argc < 6)
            FATAL_ERROR("USAGE: mapjson edge_exits <build-mode> <groups_file> <layouts_file> <map_file> [additional_map_files]\n");
        infer_separator(argv[3]);
        vector<string> map_filepaths;
        for (int i = 5; i < argc; i++)
            map_filepaths.push_back(argv[i]);
        const vector<SurfEdgeExitRecord> exits = normalize_surf_edge_exits(
            policy,
            read_json_file(argv[3], "validating Surf edge exits"),
            read_json_file(argv[4], "validating Surf edge exits"),
            map_filepaths);
        cout << "edge_exits=" << exits.size() << "\n";
    }
    else if (mode == "generate") {
        if (argc < 7)
            FATAL_ERROR("USAGE: mapjson generate <build-mode> <groups_file> <layouts_file> <output_root> <map_file> [additional_map_files]\n");
        infer_separator(argv[3]);
        vector<string> map_filepaths;
        for (int i = 6; i < argc; i++)
            map_filepaths.push_back(argv[i]);
        process_generation_tree(policy, argv[3], argv[4], argv[5], map_filepaths);
    }
    else {
        FATAL_ERROR("ERROR: <mode> must be 'checkpoints', 'edge_exits', 'generate', 'layouts', 'map', 'event_constants', 'groups', 'policy', 'sections', or 'script_registry'.\n");
    }

    return 0;
}
