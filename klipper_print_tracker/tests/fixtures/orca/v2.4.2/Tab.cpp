// Trimmed from OrcaSlicer src/slic3r/GUI/Tab.cpp for parser tests
void TabPrint::build()
{
    auto page = add_options_page(L("Quality"), "custom-gcode_quality"); // ORCA: icon only visible on placeholders
        auto optgroup = page->new_optgroup(L("Layer height"), L"param_layer_height");
        optgroup->append_single_option_line("layer_height","quality_settings_layer_height");
        optgroup->append_single_option_line("initial_layer_print_height","quality_settings_layer_height");
        optgroup = page->new_optgroup(L("Line width"), L"param_line_width");
        optgroup = page->new_optgroup(L("Seam"), L"param_seam");
        optgroup->append_single_option_line("seam_position", "quality_settings_seam#seam-position");
        optgroup = page->new_optgroup(L("Precision"), L"param_precision");
        optgroup = page->new_optgroup(L("Ironing"), L"param_ironing");
        optgroup = page->new_optgroup(L("Z contouring"), L"param_advanced");
        optgroup = page->new_optgroup(L("Wall generator"), L"param_wall_generator");
        optgroup = page->new_optgroup(L("Walls and surfaces"), L"param_wall_surface");
        optgroup = page->new_optgroup(L("Bridging"), L"param_bridge");
        optgroup = page->new_optgroup(L("Overhangs"), L"param_overhang");
    page = add_options_page(L("Strength"), "custom-gcode_strength"); // ORCA: icon only visible on placeholders
        optgroup = page->new_optgroup(L("Walls"), L"param_wall");
        optgroup->append_single_option_line("wall_loops", "strength_settings_walls#wall-loops");
        optgroup = page->new_optgroup(L("Top/bottom shells"), L"param_shell");
        optgroup = page->new_optgroup(L("Infill"), L"param_infill");
        optgroup->append_single_option_line("sparse_infill_density", "strength_settings_infill#sparse-infill-density");
        optgroup = page->new_optgroup(L("Advanced"), L"param_advanced");
    page = add_options_page(L("Speed"), "custom-gcode_speed"); // ORCA: icon only visible on placeholders
        optgroup = page->new_optgroup(L("First layer speed"), L"param_speed_first", 15);
        optgroup = page->new_optgroup(L("Other layers speed"), L"param_speed", 15);
        optgroup->append_single_option_line("outer_wall_speed", "speed_settings_other_layers_speed#outer-wall");
        optgroup = page->new_optgroup(L("Overhang speed"), L"param_overhang_speed", 15);
        optgroup = page->new_optgroup(L("Travel speed"), L"param_travel_speed", 15);
        optgroup = page->new_optgroup(L("Acceleration"), L"param_acceleration", 15);
        optgroup = page->new_optgroup(L("Junction Deviation"), L"param_junction_deviation", 15);
        optgroup = page->new_optgroup(L("Jerk(XY)"), L"param_jerk", 15);
        optgroup = page->new_optgroup(L("Advanced"), L"param_advanced", 15);
    page = add_options_page(L("Support"), "custom-gcode_support"); // ORCA: icon only visible on placeholders
        optgroup = page->new_optgroup(L("Support"), L"param_support");
        optgroup = page->new_optgroup(L("Raft"), L"param_raft");
        optgroup = page->new_optgroup(L("Support filament"), L"param_support_filament");
        optgroup = page->new_optgroup(L("Support ironing"), L"param_ironing");
        optgroup = page->new_optgroup(L("Advanced"), L"param_advanced");
        optgroup = page->new_optgroup(L("Tree supports"), L"param_support_tree");
    page = add_options_page(L("Multimaterial"), "custom-gcode_multi_material"); // ORCA: icon only visible on placeholders
        optgroup = page->new_optgroup(L("Prime tower"), L"param_tower");
        optgroup = page->new_optgroup(L("Filament for Features"), L"param_filament_for_features");
        optgroup = page->new_optgroup(L("Ooze prevention"), L"param_ooze_prevention");
        optgroup = page->new_optgroup(L("Flush options"), L"param_flush");
        optgroup = page->new_optgroup(L("Advanced"), L"advanced");
    page = add_options_page(L("Others"), "custom-gcode_other"); // ORCA: icon only visible on placeholders
        optgroup = page->new_optgroup(L("Skirt"), L"param_skirt");
        optgroup = page->new_optgroup(L("Brim"), L"param_adhension");
        optgroup = page->new_optgroup(L("Special mode"), L"param_special");
        optgroup = page->new_optgroup(L("Fuzzy Skin"), L"fuzzy_skin");
        optgroup = page->new_optgroup(L("G-code output"), L"param_gcode");
        optgroup = page->new_optgroup(L("Change extrusion role G-code"), L"param_gcode", 0);
        optgroup = page->new_optgroup(L("Post-processing Scripts"), L"param_gcode", 0);
        optgroup = page->new_optgroup(L("Notes"), "note", 0);
}

void TabFilament::build()
{
    auto page = add_options_page(L("Filament"), "custom-gcode_filament"); // ORCA: icon only visible on placeholders
        auto optgroup = page->new_optgroup(L("Basic information"), L"param_information");
        optgroup = page->new_optgroup(L("Flow ratio and Pressure Advance"), L"param_flow_ratio_and_pressure_advance");
        optgroup->append_single_option_line("filament_flow_ratio", "material_flow_ratio_and_pressure_advance#flow-ratio", 0);
        optgroup = page->new_optgroup(L("Print chamber temperature"), L"param_chamber_temp");
        optgroup = page->new_optgroup(L("Print temperature"), L"param_extruder_temp");
        line.append_option(optgroup->get_option("nozzle_temperature", 0));
        optgroup = page->new_optgroup(L("Bed temperature"), L"param_bed_temp");
            else */if (opt_key == "nozzle_temperature") 
        optgroup = page->new_optgroup(L("Volumetric speed limitation"), L"param_volumetric_speed");
    page = add_options_page(L("Cooling"), "custom-gcode_cooling_fan"); // ORCA: icon only visible on placeholders
        optgroup = page->new_optgroup(L("Cooling for specific layer"), L"param_cooling_specific_layer");
        optgroup = page->new_optgroup(L("Part cooling fan"), L"param_cooling_part_fan");
        optgroup = page->new_optgroup(L("Auxiliary part cooling fan"), L"param_cooling_aux_fan");
        optgroup = page->new_optgroup(L("Exhaust fan"),L"param_cooling_exhaust");
    page = add_options_page(L("Advanced"), "custom-gcode_advanced"); // ORCA: icon only visible on placeholders
        optgroup = page->new_optgroup(L("Filament start G-code"), L"param_gcode", 0);
        optgroup = page->new_optgroup(L("Change extrusion role G-code"), L"param_gcode", 0);
        optgroup = page->new_optgroup(L("Filament end G-code"), L"param_gcode", 0);
    page = add_options_page(L("Multimaterial"), "custom-gcode_multi_material"); // ORCA: icon only visible on placeholders
        optgroup = page->new_optgroup(L("Wipe tower parameters"), "param_tower");
        optgroup = page->new_optgroup(L("Multi Filament"));
        optgroup = page->new_optgroup(L("Tool change parameters with single extruder MM printers"), "param_toolchange");
        optgroup = page->new_optgroup(L("Tool change parameters with multi extruder MM printers"), "param_toolchange_multi_extruder");
    page = add_options_page(L("Dependencies"), "advanced");
        optgroup = page->new_optgroup(L("Compatible printers"), "param_dependencies_printers");
        optgroup = page->new_optgroup(L("Compatible process profiles"), "param_dependencies_presets");
    page = add_options_page(L("Notes"), "custom-gcode_note"); // ORCA: icon only visible on placeholders
        optgroup = page->new_optgroup(L("Notes"),"note", 0);
}

void TabPrinter::build_fff()
{
    auto   *nozzle_diameter = dynamic_cast<const ConfigOptionFloats*>(m_config->option("nozzle_diameter"));
            static_cast<const ConfigOptionFloats*>(parent_preset->config.option("nozzle_diameter"))->values.size();
    auto page = add_options_page(L("Basic information"), "custom-gcode_object-info"); // ORCA: icon only visible on placeholders
    auto optgroup = page->new_optgroup(L("Printable space"), "param_printable_space");
        optgroup = page->new_optgroup(L("Advanced"), L"param_advanced");
        optgroup  = page->new_optgroup(L("Cooling Fan"), "param_cooling_fan");
        optgroup = page->new_optgroup(L("Extruder Clearance"), "param_extruder_clearance");
        optgroup = page->new_optgroup(L("Adaptive bed mesh"), "param_adaptive_mesh");
        optgroup = page->new_optgroup(L("Accessory"), "param_accessory");
    page = add_options_page(L("Machine G-code"), "custom-gcode_gcode"); // ORCA: icon only visible on placeholders
        optgroup = page->new_optgroup(L("File header G-code"), L"param_gcode", 0);
        optgroup = page->new_optgroup(L("Machine start G-code"), L"param_gcode", 0);
        optgroup = page->new_optgroup(L("Machine end G-code"), L"param_gcode", 0);
        optgroup              = page->new_optgroup(L("Printing by object G-code"), L"param_gcode", 0);
        optgroup = page->new_optgroup(L("Before layer change G-code"),"param_gcode", 0);
        optgroup = page->new_optgroup(L("Layer change G-code"), L"param_gcode", 0);
        optgroup = page->new_optgroup(L("Timelapse G-code"), L"param_gcode", 0);
        optgroup              = page->new_optgroup(L("Clumping Detection G-code"), L"param_gcode", 0);
        optgroup = page->new_optgroup(L("Change filament G-code"), L"param_gcode", 0);
        optgroup = page->new_optgroup(L("Change extrusion role G-code"), L"param_gcode", 0);
        optgroup = page->new_optgroup(L("Pause G-code"), L"param_gcode", 0);
        optgroup = page->new_optgroup(L("Template Custom G-code"), L"param_gcode", 0);
    page = add_options_page(L("Notes"), "custom-gcode_note"); // ORCA: icon only visible on placeholders
        optgroup = page->new_optgroup(L("Notes"), "note", 0);
}

void TabPrinter::build_unregular_pages()
{
        auto page     = add_options_page(L("Multimaterial"), "custom-gcode_multi_material", true); // ORCA: icon only visible on placeholders
        auto optgroup = page->new_optgroup(L("Single extruder multi-material setup"), "param_multi_material");
                                static_cast<const ConfigOptionFloats*>(m_config->option("nozzle_diameter"))->values;
                                        new_conf.set_key_value("nozzle_diameter", new ConfigOptionFloats(nozzle_diameters));
        optgroup = page->new_optgroup(L("Wipe tower"), "param_tower");
        optgroup = page->new_optgroup(L("Single extruder multi-material parameters"), "param_settings");
        optgroup = page->new_optgroup(L("Advanced"), L"param_advanced");
        auto optgroup = page->new_optgroup(L("Basic information"), L"param_information", -1, true);
            optgroup->append_single_option_line("nozzle_diameter", "printer_extruder_basic_information#nozzle-diameter", extruder_idx);
                if (is_SEMM && m_extruders_count > 1 && opt_key.find_first_of("nozzle_diameter") != std::string::npos)
                    std::vector<double> nozzle_diameters = static_cast<const ConfigOptionFloats*>(m_config->option("nozzle_diameter"))->values;
                        new_conf.set_key_value("nozzle_diameter", new ConfigOptionFloats(nozzle_diameters));
            optgroup = page->new_optgroup(L("Layer height limits"), L"param_layer_height");
            optgroup = page->new_optgroup(L("Position"), L"param_position");
            optgroup = page->new_optgroup(L("Retraction"), L"param_retraction");
            optgroup = page->new_optgroup(L("Z-Hop"), L"param_extruder_lift_enforcement");
            optgroup = page->new_optgroup(L("Retraction when switching material"), L"param_retraction_material_change");
}

