#pragma once
#include "rt.h"
#include <math.h>

static inline int mouse_sensitivity_percent(const char* value){
  double factor=atof(value);
  if(!(factor>0)) factor=1;
  if(factor<.1) factor=.1;
  if(factor>5) factor=5;
  return (int)(factor*100+.5);
}

static inline i32 mouse_axis(double value){
  if(value>32767) return 32767;
  if(value< -32767) return -32767;
  return (i32)value;
}

static inline void mouse_stick(i32 dx, i32 dy, u64 elapsed, int sensitivity, int invert, i32* x, i32* y){
  if(!dx && !dy){ *x=*y=0; return; }
  double scale=32767.0*2500000.0*pow(250.0,(sensitivity-10)/490.0)/(double)elapsed;
  *x=mouse_axis(dx*scale*((invert&1)?-1:1));
  *y=mouse_axis(dy*scale*((invert&2)?1:-1));
}
