"""Parámetros compartidos del protocolo, con tiempos explícitos en segundos."""
from dataclasses import dataclass
import math

from .model import MeshError


@dataclass(frozen=True)
class Protocol:
    mode: str = "displacement"
    displacement: float = 0.1
    compression_percent: float = 10.0
    force: float = 1.0
    ramp_time: float = 0.1
    step1_duration: float = 1.0
    step1_dt: float = 0.01
    step2_duration: float = 7.0
    step2_dt: float = 0.01

    def validate(self):
        if self.mode not in ("displacement","percent","force"):
            raise MeshError("El control debe ser desplazamiento, porcentaje o fuerza.")
        amount = {"displacement":self.displacement,"percent":self.compression_percent,"force":self.force}[self.mode]
        values = (amount,self.ramp_time,self.step1_duration,self.step1_dt,self.step2_duration,self.step2_dt)
        if any(isinstance(v,bool) or not math.isfinite(v) or v<=0 for v in values):
            raise MeshError("La magnitud, los tiempos y los incrementos deben ser números positivos y finitos.")
        if self.mode=="percent" and amount>=100:
            raise MeshError("La compresión porcentual debe ser menor que 100 %.")
        if self.ramp_time>self.step1_duration:
            raise MeshError("La rampa debe terminar dentro del primer paso.")
        for duration,dt,label in ((self.step1_duration,self.step1_dt,"paso 1"),
                                   (self.step2_duration,self.step2_dt,"paso 2"),
                                   (self.ramp_time,self.step1_dt,"rampa")):
            count = duration/dt
            if count<1 or not math.isclose(count,round(count),rel_tol=1e-10,abs_tol=1e-8):
                raise MeshError(f"La duración de {label} debe ser un múltiplo entero de su incremento de tiempo.")
        return self

    def displacement_for(self,height):
        self.validate()
        if self.mode=="force": return None
        value = self.displacement if self.mode=="displacement" else height*self.compression_percent/100
        if value>=height:
            raise MeshError(f"La compresión ({value:g} m) debe ser menor que la separación entre tapas ({height:g} m).")
        return value

    def description(self):
        amount = {"displacement":f"{self.displacement:g} m", "percent":f"{self.compression_percent:g} %",
                  "force":f"{self.force:g} N totales"}[self.mode]
        return f"Compresión: {amount}; rampa {self.ramp_time:g} s; duración total {self.step1_duration+self.step2_duration:g} s."
