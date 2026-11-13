#ifndef LECTOR_REGLA_HPP
#define LECTOR_REGLA_HPP

#include "ap_int.h"

constexpr int MAX_W = 1280;
constexpr int MAX_H = 720;

typedef ap_uint<8> pixel_t;
typedef ap_uint<11> x_coor_t;
typedef ap_uint<10> y_coor_t;

// definiciones de error
typedef ap_uint<4> rl_err_t;
#define RL_OK 0
#define RL_ERR_REGLA_NO_ENCONTRADA 1
#define RL_ERR_INVALID_ARGS 2

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
);

// TODO
#endif


