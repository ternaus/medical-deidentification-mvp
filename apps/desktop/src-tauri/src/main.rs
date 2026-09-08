#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    medical_deid_lib::run();
}
