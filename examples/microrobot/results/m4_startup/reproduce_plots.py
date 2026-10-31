"""Rebuild M4 reviewer plots from archived extrema-preserving plot previews.

Run: MPLCONFIGDIR=/tmp/opentcad-mpl python reproduce_plots.py
No ngspice, PDK, local_runs or raw .dat files are needed. Metrics are NOT
recomputed from these decimated previews; use the archived full-waveform reviews.
"""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
HERE=Path(__file__).resolve().parent
CASES=[('driver_pair','Direct pair','#a84632'),('driver_and','Standard-Vt AND','#8a66a9'),('driver_lvt_08ms','Final-pulldown LVT AND','#147b8a'),('driver_forced_low','Driver pins forced zero','#4a6350')]
def read(name):
 a=np.genfromtxt(HERE/name/'plot_preview.csv.gz',delimiter=',',names=True)
 return {n:a[n] for n in a.dtype.names}
fig,axes=plt.subplots(5,1,figsize=(9,11),sharex=True,constrained_layout=True)
for name,label,color in CASES:
 d=read(name);w=d['time_s']<=.0004;t=d['time_s'][w]*1e6
 axes[0].plot(t,d['driver_ready_V'][w],label=label,color=color)
 axes[1].plot(t,d['metal_A_minus_mid_V'][w]*1000,color=color)
 if name in ['driver_lvt_08ms','driver_forced_low']:axes[2].plot(t,d['metal_A_minus_mid_V'][w]*1000,label=label,color=color)
 axes[3].plot(t,d['eta_A_V'][w]*1e6,color=color)
 if name in ['driver_lvt_08ms','driver_forced_low']:axes[4].plot(t,d['eta_A_V'][w]*1e6,label=label,color=color)
axes[0].set_ylabel('Driver enable (V)');axes[1].set_ylabel('Metal A − midpoint\n(mV)');axes[2].set_ylabel('Metal A − midpoint\nzoom (mV)');axes[3].set_ylabel('Local eta A (µV)');axes[4].set_ylabel('Local eta A\nzoom (µV)');axes[4].set_xlabel('Time from dark operating point (µs)')
axes[0].legend(fontsize=8,ncol=2);axes[2].legend(fontsize=8);axes[4].legend(fontsize=8)
for ax in axes:ax.grid(alpha=.2)
fig.suptitle('Exploratory finite-PV cold clamp — TT, 50 ns maximum step\nLVT changes only final qualifier pulldown; forced zero is an ideal diagnostic',fontsize=11)
fig.savefig(HERE/'cold_clamp_and_local_eta.png',dpi=160)
fig,axes=plt.subplots(2,1,figsize=(9,6),sharex=True,constrained_layout=True)
for name,label,color in CASES[:3]:
 d=read(name);w=(d['time_s']>=480e-6)&(d['time_s']<=570e-6);t=d['time_s'][w]*1e6
 axes[0].plot(t,d['logic_V'][w],color=color,label=label+' logic')
 axes[0].plot(t,d['actuator_V'][w],color=color,ls=':',label=label+' actuator')
 axes[1].plot(t,d['native_reset_V'][w]/np.maximum(d['logic_V'][w],.1),color=color,label=label+' native reset / logic')
 axes[1].plot(t,d['driver_ready_V'][w]/np.maximum(d['actuator_V'][w],.1),color=color,ls='--',label=label+' driver enable / actuator')
axes[1].axhline(.9,color='.45',lw=.8,ls=':');axes[0].set_ylabel('Supply (V)');axes[1].set_ylabel('Relative signal');axes[1].set_xlabel('Time from dark operating point (µs)')
for ax in axes:ax.grid(alpha=.2);ax.legend(fontsize=7,ncol=2)
fig.suptitle('Nominal release-window diagnostics — not a reset-threshold specification',fontsize=11)
fig.savefig(HERE/'release_window.png',dpi=160)
# Historical reset comparison: retain original PNG, also offer a reproducible
# view of the same100ns cases from compact archived window previews.
fig,axes=plt.subplots(3,1,figsize=(8,7),sharex=True,constrained_layout=True)
for name,label,color in [('reset_latch','Original latch','#a84632'),('reset_current_limited_100ns','Current-limited','#147b8a')]:
 d=np.genfromtxt(HERE/(name+'_preview.csv.gz'),delimiter=',',names=True);t=d['time_s']*1e6
 axes[0].plot(t,d['logic_V'],color=color,label=label+' logic');axes[0].plot(t,d['actuator_V'],color=color,ls=':',label=label+' actuator')
 axes[1].plot(t,d['reset_V']/np.maximum(d['logic_V'],.1),color=color,label=label+' reset / logic');axes[1].plot(t,d['ready_V']/np.maximum(d['actuator_V'],.1),color=color,ls=':',label=label+' ready / actuator')
 e=d['resetlogic_energy_nJ'];offset=np.interp(490,t,e);axes[2].plot(t,(e-offset)*1000,color=color,label=label+' logic-port delivery')
axes[0].axhline(1.5,color='.45',ls='--',lw=.8);axes[0].set_ylabel('Supply (V)');axes[1].set_ylabel('Relative signal');axes[2].set_ylabel('Converter energy (pJ)');axes[2].set_xlabel('Time from dark operating point (µs)');axes[1].set_ylim(-.4,1.15)
for ax in axes:ax.grid(alpha=.2);ax.legend(fontsize=7)
fig.suptitle('Historical nominal reset comparison — 100 ns maximum step\nFull-waveform metrics remain in case reports',fontsize=11)
fig.savefig(HERE/'reset_comparison_reproduced.png',dpi=160)
