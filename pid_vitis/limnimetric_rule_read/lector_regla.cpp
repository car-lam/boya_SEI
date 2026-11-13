#include "lector_regla.hpp"

void lector_regla(
    // Entradas
    pixel_t* imagen_pixeles,
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
    #pragma HLS INTERFACE m_axi port=imagen_pixeles offset=slave bundle=gmem depth=921600
    #pragma HLS INTERFACE s_axilite port=alto
    #pragma HLS INTERFACE s_axilite port=ancho
    #pragma HLS INTERFACE s_axilite port=umbral

    #pragma HLS INTERFACE s_axilite port=col_min
    #pragma HLS INTERFACE s_axilite port=fil_min
    #pragma HLS INTERFACE s_axilite port=col_max
    #pragma HLS INTERFACE s_axilite port=fil_max
    #pragma HLS INTERFACE s_axilite port=error

    #pragma HLS INTERFACE s_axilite port=return

    if (ancho > MAX_W || alto > MAX_H) {
        error = RL_ERR_INVALID_ARGS;
        return;
    }

    x_coor_t col_min_l = ancho;
    y_coor_t fil_min_l = alto;
    x_coor_t col_max_l = 0;
    y_coor_t fil_max_l = 0;

    int posicion_actual = 0;


    // Detección de la regla
    for (y_coor_t fila = 0; fila < alto; fila++)
    {
        #pragma HLS LOOP_TRIPCOUNT max=MAX_H

        for (x_coor_t col = 0; col < ancho; col++)
        {
            #pragma HLS PIPELINE II=1
            #pragma HLS LOOP_TRIPCOUNT max=MAX_W
            // is_regla corresponde a la condición que aún hay que hacer
            if (*(imagen_pixeles + posicion_actual) > umbral)
            {
                if (col < col_min_l) col_min_l = col;
                if (fila < fil_min_l) fil_min_l = fila;
                if (col > col_max_l) col_max_l = col;
                if (fila > fil_max_l) fil_max_l = fila;
            }

            posicion_actual += 1;
        }
    }

    // Salida de error
    if (col_min_l == ancho) error = RL_ERR_REGLA_NO_ENCONTRADA;
    else error = RL_OK;

    // Asignaciones a salidas
    col_min = col_min_l;
    fil_min = fil_min_l;
    col_max = col_max_l;
    fil_max = fil_max_l;
}
