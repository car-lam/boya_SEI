#include "lector_regla.hpp"

void lector_regla(
    // Entradas
    pixel_t* inicio,
    int alto,
    int ancho,
    ap_uint<8> umbral,
    // Salidas
    x_coor_t &col_min,
    y_coor_t &fil_min,
    x_coor_t &col_max,
    y_coor_t &fil_max,
    rl_err_t &error
) {
    #pragma HLS INTERFACE axis port=inicio
}