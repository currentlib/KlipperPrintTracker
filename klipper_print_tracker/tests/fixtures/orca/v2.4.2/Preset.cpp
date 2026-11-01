// Trimmed from OrcaSlicer src/libslic3r/Preset.cpp for parser tests
static std::vector<std::string> s_Preset_print_options {
    "layer_height", "wall_loops", "sparse_infill_density", "outer_wall_speed", "seam_position", "initial_layer_print_height"
};
static std::vector<std::string> s_Preset_filament_options {
    "nozzle_temperature", "filament_flow_ratio", "filament_retraction_length"
};
static std::vector<std::string> s_Preset_machine_limits_options {
    "machine_max_speed_x"
};
static std::vector<std::string> s_Preset_printer_options {
    "printable_height"
};
