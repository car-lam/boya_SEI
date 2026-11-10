#ifndef LECTOR_REGLA_HPP
#define LECTOR_REGLA_HPP

#include "ap_int.h"

constexpr int MAX_W = 1280;
constexpr int MAX_H = 720;

typedef ap_uint<32> pixel_t;
typedef ap_uint<11> x_coor_t;
typedef ap_uint<10> y_coor_t;

// definiciones de error
typedef ap_uint<4> err;
#define RL_OK = 0;
#define RL_ERR_IMAGEN_NO_ACCESIBLE = 1;
#define RL_ERR_REGLA_NO_ENCONTRADA = 2;

// TODO



#endif