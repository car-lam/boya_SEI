#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <string.h>
#include <string>
#include <sys/types.h>
#include <vector>
#include "lector_regla.hpp"

#ifndef TB_DATOS
#define TB_DATOS "/home/carlos/codigo/universidad/cursos/SEI/proyecto/pid_vitis/limnimetric_rule_read/tb_datos/"
#endif

int main(){
    int ancho, alto;
    int u, u_temp;

    std::string base = std::string(TB_DATOS) + "ref06_m_blankensee_lago_olas";

    // Leer el resultado esperado
    std::ifstream e(base + "_esperado.txt");
    std::string etiqueta;

    if (!e) {printf("No se pudo abrir esperado.txt"); return 1;}

    // Esperados en int: >> lee números sin depender de cómo Xilinx definió >> para ap_uint
    int exp_cmin = -1, exp_fmin = -1, exp_cmax = -1, exp_fmax = -1, exp_err = -1;

    while(e >> etiqueta) {
        if      (etiqueta == "dims")    e >> ancho >> alto;
        else if (etiqueta == "umbral")  {e >> u_temp; u = u_temp;}
        else if (etiqueta == "minmax")  e >> exp_cmin >> exp_fmin >> exp_cmax >> exp_fmax >> exp_err;
        else std::getline(e, etiqueta);
    }

    // Leer el .raw a bytes y copiarlo a pixel_t
    std::vector<unsigned char> bytes(ancho * alto);
    FILE* f = fopen((base + ".raw").c_str(), "rb");
    if (!f) {printf("No abre %s.raw\n", base.c_str()); return 1; }
    size_t n = fread(bytes.data(), 1, bytes.size(), f);
    fclose(f);
    if (n != bytes.size()) { printf("Se leyó %zu de %zu bytes\n", n, bytes.size()); return 1;}

    std::vector<pixel_t> img(bytes.begin(), bytes.end());

    // Llamar al DUT
    x_coor_t col_min, col_max;
    y_coor_t fil_min, fil_max;
    rl_err_t err;
    lector_regla(img.data(), alto, ancho, u, col_min, fil_min, col_max, fil_max, err);

    // Comparar resultado obtenido y esperado
    int errores = 0;
    if (col_min != exp_cmin) { printf("Col_min: real -> %d, exp -> %d\n", (int)col_min, exp_cmin); errores++; }
    if (fil_min != exp_fmin) { printf("Fil_min: real -> %d, exp -> %d\n", (int)fil_min, exp_fmin); errores++; }
    if (col_max != exp_cmax) { printf("Col_max: real -> %d, exp -> %d\n", (int)col_max, exp_cmax); errores++; }
    if (fil_max != exp_fmax) { printf("Fil_max: real -> %d, exp -> %d\n", (int)fil_max, exp_fmax); errores++; }
    if (err     != exp_err)  { printf("Error:   real -> %d, exp -> %d\n", (int)err,     exp_err);  errores++; }

    if (errores == 0) printf("PASS\n");
    else              printf("FAIL (%d diferencias)\n", errores);
    return errores ? 1 : 0;   // Vitis decide pass/fail con este valor
}
