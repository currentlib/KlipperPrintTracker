// Trimmed from OrcaSlicer src/libslic3r/PrintConfig.cpp for parser tests
void PrintConfigDef::init_common_params()
{

    def = this->add("layer_height", coFloat);
    def->label = L("Layer height");
    def->category = L("Quality");
    def->tooltip = L("Slicing height for each layer. Smaller layer height means more accurate and more printing time.");
    def->sidetext = L("mm");	// millimeters, CIS languages need translation
    def->min = 0;
    def->set_default_value(new ConfigOptionFloat(INITIAL_LAYER_HEIGHT));

    def = this->add("outer_wall_speed", coFloat);
    def->label = L("Outer wall");
    def->category = L("Speed");
    def->tooltip = L("Speed of outer wall which is outermost and visible. "
                     "It's used to be slower than inner wall speed to get better quality.");
    def->sidetext = L("mm/s");	// millimeters per second, CIS languages need translation
    def->min = 1;
    def->mode = comAdvanced;
    def->set_default_value(new ConfigOptionFloat(60));

    def = this->add("filament_flow_ratio", coFloats);
    def->label = L("Flow ratio");
    def->tooltip = L("The material may have volumetric change after switching between molten and crystalline states. "
                     "This setting changes all extrusion flow of this filament in G-code proportionally. "
                     "The recommended value range is between 0.95 and 1.05. "
                     "You may be able to tune this value to get a nice flat surface if there is slight overflow or underflow.");
    def->min = 0;
    def->max = 2;
    def->mode = comAdvanced;
    def->nullable = true;
    def->set_default_value(new ConfigOptionFloatsNullable { 1. });

    def = this->add("sparse_infill_density", coPercent);
    def->label = L("Sparse infill density");
    def->category = L("Strength");
    // xgettext:no-c-format, no-boost-format
    def->tooltip = L("Density of internal sparse infill, 100% turns all sparse infill into solid infill and internal solid infill pattern will be used.");
    def->sidetext = "%";
    def->min = 0;
    def->max = 100;
    def->set_default_value(new ConfigOptionPercent(20));

    def = this->add("initial_layer_print_height", coFloat);
    def->label = L("First layer height");
    def->category = L("Quality");
    def->tooltip = L("Height of the first layer. Making the first layer height thicker can improve build plate adhesion.");
    def->sidetext = L("mm");	// millimeters, CIS languages need translation
    def->min = 0;
    def->set_default_value(new ConfigOptionFloat(0.2));

    def = this->add("nozzle_diameter", coFloats);
    def->label = L("Nozzle diameter");
    def->tooltip = L("The diameter of nozzle.");
    def->sidetext = L("mm");	// millimeters, CIS languages need translation
    def->mode = comAdvanced;
    def->max = 100;
    def->set_default_value(new ConfigOptionFloats { 0.4 });

    def = this->add("wall_loops", coInt);
    def->label = L("Wall loops");
    def->category = L("Strength");
    def->tooltip = L("Number of walls of every layer.");
    def->min = 0;
    def->max = 1000;
    def->set_default_value(new ConfigOptionInt(2));

    def = this->add("seam_position", coEnum);
    def->label = L("Seam position");
    def->category = L("Quality");
    def->tooltip = L("The start position to print each part of outer wall.");
    def->enum_keys_map = &ConfigOptionEnum<SeamPosition>::get_enum_values();
    def->enum_values.push_back("nearest");
    def->enum_values.push_back("aligned");
    def->enum_values.push_back("aligned_back");
    def->enum_values.push_back("back");
    def->enum_values.push_back("random");
    def->enum_labels.push_back(L("Nearest"));
    def->enum_labels.push_back(L("Aligned"));
    def->enum_labels.push_back(L("Aligned back"));
    def->enum_labels.push_back(L("Back"));
    def->enum_labels.push_back(L("Random"));
    def->mode = comSimple;
    def->set_default_value(new ConfigOptionEnum<SeamPosition>(spAligned));

    def = this->add("nozzle_temperature", coInts);
    def->label = L("Other layers");
    def->tooltip = L("Nozzle temperature for layers after the initial one.");
    def->sidetext = L(u8"\u2103" /* °C */);	// degrees Celsius, CIS languages need translation
    def->full_label = L("Nozzle temperature");
    def->min = 0;
    def->max = max_temp;
    def->set_default_value(new ConfigOptionInts { 200 });
}

void PrintConfigDef::init_sla_params()
{
}

void PrintConfigDef::init_extruder_option_keys()
{
    // ConfigOptionFloats, ConfigOptionPercents, ConfigOptionBools, ConfigOptionStrings
    m_extruder_option_keys = {
        "extruder_type", "nozzle_diameter", "default_nozzle_volume_type", "min_layer_height", "max_layer_height", "extruder_offset",
        "extruder_printable_height", "nozzle_volume", "nozzle_type", "nozzle_flush_dataset",
        "retraction_length", "z_hop", "z_hop_types", "travel_slope", "retract_lift_above", "retract_lift_below", "retract_lift_enforce", "retraction_speed", "deretraction_speed",
        "retract_before_wipe", "retract_restart_extra", "retraction_minimum_travel", "wipe", "wipe_distance",
        "retract_when_changing_layer", "retract_length_toolchange", "retract_restart_extra_toolchange", "extruder_colour",
        "default_filament_profile","retraction_distances_when_cut","long_retractions_when_cut"
    };

    m_extruder_retract_keys = {
        "deretraction_speed",
        "long_retractions_when_cut",
        "retract_before_wipe",
        "retract_lift_above",
        "retract_lift_below",
        "retract_lift_enforce",
        "retract_restart_extra",
        "retract_when_changing_layer",
        "retraction_distances_when_cut",
        "retraction_length",
        "retraction_minimum_travel",
        "retraction_speed",
        "travel_slope",
        "wipe",
        "wipe_distance",
        "z_hop",
        "z_hop_types"
    };
    assert(std::is_sorted(m_extruder_retract_keys.begin(), m_extruder_retract_keys.end()));
}
