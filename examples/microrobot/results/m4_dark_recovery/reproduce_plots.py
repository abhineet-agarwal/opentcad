"""Plot archived nominal dark/recovery previews; no PDK or raw data required.

Run: MPLCONFIGDIR=/tmp/opentcad-mpl python reproduce_plots.py
Previews are for visualization only. Metrics and pass/fail checks use the full
adaptive transient, including every excluded/qualified edge.
"""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import json
HERE=Path(__file__).resolve().parent

def plot():
    path=HERE/'reference_preview.csv.gz'
    if not path.exists():
        raise SystemExit('No preview archived: execution/result review is pending.')
    d=np.genfromtxt(path,delimiter=',',names=True)
    t=d['time_s']*1e3
    fig,ax=plt.subplots(5,1,figsize=(9,11),sharex=True,constrained_layout=True)
    ax[0].plot(t,d['light_W_m2'],color='#c08b22',label='Saved illumination')
    history=np.array(json.loads((HERE/'criteria.json').read_text())['illumination_PWL_s_W_m2'])
    future=np.r_[t[-1],history[history[:,0]*1e3>t[-1],0]*1e3]
    ax[0].plot(future,np.interp(future,history[:,0]*1e3,history[:,1]),color='.4',ls='--',label='Planned light, not simulated')
    ax[1].plot(t,d['logic_V'],label='Logic',color='#8b4234')
    ax[1].plot(t,d['actuator_V'],label='Actuator',color='#167889')
    ax[1].plot(t,d['midpoint_V'],label='PV midpoint',color='#536847',ls=':')
    ax[1].axhline(1.6,color='.5',ls='--',lw=.8,label='Qualified-edge rail floor')
    meaningful=(d['logic_V']>=1)&(d['actuator_V']>=.5)
    ax[2].plot(t,np.where(meaningful,d['native_reset_V']/np.maximum(d['logic_V'],.1),np.nan),label='Reset / logic',color='#8b4234')
    ax[2].plot(t,np.where(meaningful,d['driver_ready_V']/np.maximum(d['actuator_V'],.1),np.nan),label='Driver enable / actuator',color='#167889')
    ax[2].axhline(.9,color='.5',lw=.6,ls=':');ax[2].axhline(.1,color='.5',lw=.6,ls=':')
    ax[3].plot(t,d['metal_A_minus_mid_V']*1e3,label='A',color='#8b4234')
    ax[3].plot(t,d['metal_B_minus_mid_V']*1e3,label='B',color='#167889')
    ax[4].plot(t,d['eta_A_V'],label='A',color='#8b4234')
    ax[4].plot(t,d['eta_B_V'],label='B',color='#167889')
    labels=['Light (W/m²)','Rail voltage (V)','Relative control signal','Metal − midpoint (mV)','Local eta (V)']
    for a,label in zip(ax,labels):
        a.set_ylabel(label);a.grid(alpha=.2);a.legend(fontsize=8,loc='best')
        a.axvspan(1.6,3.1,color='.5',alpha=.12)
        for boundary in [1.5,1.6,3.1,4.0]:a.axvline(boundary,color='.65',lw=.6,ls=':')
        a.axvspan(float(t[-1]),4.5,color='.7',alpha=.18)
        a.axvline(float(t[-1]),color='#a93a32',lw=1,ls='--')
        a.set_xlim(float(t.min()),4.5)
    ax[-1].set_xlabel('Time from initial dark operating point (ms)')
    ax[0].annotate(f'Abort {t[-1]:.6f} ms',xy=(float(t[-1]),0),xytext=(2.7,600),arrowprops={'arrowstyle':'->','color':'#a93a32'},fontsize=9,color='#a93a32')
    ax[1].text(3.45,.75,'Not simulated',color='.4',fontsize=10)
    fig.suptitle('Partial nominal TT dark transient — recovery not reached\nRatios shown only at logic≥1 V, actuator≥0.5 V; gray future is unobserved',fontsize=11)
    fig.savefig(HERE/'dark_recovery_overview.png',dpi=160)

def plot_prefix_pair():
    paths=[HERE/'prefix_50ns_preview.csv.gz',HERE/'prefix_25ns_preview.csv.gz']
    if not all(p.exists() for p in paths):
        return
    fig,ax=plt.subplots(3,1,figsize=(9,8),sharex=True,constrained_layout=True)
    for p,label,ls in zip(paths,['50 ns','25 ns'],['-','--']):
        d=np.genfromtxt(p,delimiter=',',names=True);t=d['time_s']*1e3
        ax[0].plot(t,d['logic_V'],color='#8b4234',ls=ls,label=label+' logic')
        ax[0].plot(t,d['actuator_V'],color='#167889',ls=ls,label=label+' actuator')
        meaningful=(d['logic_V']>=1)&(d['actuator_V']>=.5)
        ax[1].plot(t,np.where(meaningful,d['native_reset_V']/np.maximum(d['logic_V'],.1),np.nan),color='#8b4234',ls=ls,label=label+' reset / logic')
        ax[1].plot(t,np.where(meaningful,d['driver_ready_V']/np.maximum(d['actuator_V'],.1),np.nan),color='#167889',ls=ls,label=label+' enable / actuator')
        ax[2].plot(t,d['eta_A_V'],color='#8b4234',ls=ls,label=label+' eta A')
        ax[2].plot(t,d['eta_B_V'],color='#167889',ls=ls,label=label+' eta B')
    ax[0].axhline(1.6,color='.5',lw=.7,ls=':')
    for a,label in zip(ax,['Rails (V)','Relative control signal','Local eta (V)']):
        a.set_ylabel(label);a.grid(alpha=.2);a.legend(fontsize=8,ncol=2);a.axvspan(1.6,2.2,color='.5',alpha=.12);a.set_xlim(0,2.2)
    ax[-1].set_xlabel('Time (ms)')
    fig.suptitle('Separate 2.2 ms power-down prefixes — 50/25 ns comparison\nComplete original future light history retained; no relight or recovery in this prefix',fontsize=11)
    fig.savefig(HERE/'powerdown_prefix_pair.png',dpi=160)

if __name__=='__main__':
    plot()
    plot_prefix_pair()
