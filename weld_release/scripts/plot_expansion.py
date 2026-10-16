"""ACL-width scientific figures, exported with inspectable figure data."""
from pathlib import Path
import json,sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
from matplotlib.patches import Patch
R=Path(__file__).resolve().parents[1];A=R/'data';F=R/'figures';F.mkdir(exist_ok=True)
SCENES=['graph','code_review','analytics','incident','appworld'];SN=['Graph','Code','SQL','Incident','Business'];MODELS=['deepseek','kimi','qwen','gemma','glm','minimax','gemini','gemini37','grok','luna'];MN=['DeepSeek V4 Pro','Kimi K2.6','Qwen3.8 Flash','Gemma 4 31B','GLM-5.3 Flash','MiniMax M3','Gemini 3.8 Flash','Gemini 3.7 Flash','Grok 4.3','GPT-6 Luna']
COLORS=['#4267A8','#BA792B','#7F6AAB','#3E8585','#A04D74']
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.titlesize':10,'axes.labelsize':9,'pdf.fonttype':42,'svg.fonttype':'none','axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.6,'grid.color':'#dddddd','grid.linewidth':.5})
def read(n):return pd.read_csv(A/(n+'.csv'))
def finish(fig,name):
 for ext in ['pdf','svg','png']:fig.savefig(F/(name+'.'+ext),dpi=220,bbox_inches='tight')
 plt.close(fig)
def main():
 global A,F,MODELS,MN
 if '--available' in sys.argv:A=R/'analysis/available';F=R/'figures/available';F.mkdir(exist_ok=True)
 metadata=read('model_metadata');MODELS=metadata.model.tolist();MN=metadata.label.tolist();n_open=int(metadata.group.eq('Open-weight family API').sum())
 p=read('native_work_pairs');p['category']=p.relation.replace({'a_dominates':'Dominance','b_dominates':'Dominance','equal':'Equal','tradeoff':'Trade-off'})
 count=p.groupby(['scene','category']).size().unstack(fill_value=0).reindex(SCENES).reindex(columns=['Equal','Dominance','Trade-off'],fill_value=0);count.to_csv(A/'figure1_counts.csv')
 fig,axs=plt.subplots(1,2,figsize=(7.1,2.8),gridspec_kw={'width_ratios':[1.1,1]});left=np.zeros(5)
 for cat,color in zip(count.columns,['#b7bec5','#4267A8','#BA792B']):
  vals=count[cat].to_numpy();axs[0].barh(SN,vals,left=left,label=cat,color=color,height=.62);left+=vals
 for i,n in enumerate(left):axs[0].text(n+2,i,str(int(n)),va='center',fontsize=8)
 axs[0].invert_yaxis();axs[0].set_xlabel('Jointly valid model pairs');axs[0].set_xlim(0,max(left)*1.15);axs[0].set_title('(a) Recorded native-work relation');axs[0].legend(frameon=False,fontsize=8,loc='upper center',bbox_to_anchor=(.5,-.22),ncol=3)
 pc=read('native_work_pair_components');pc=pc[pc.primary & (pc.work_a!=pc.work_b)].copy();pc['saving']=1-pc[['work_a','work_b']].min(axis=1)/pc[['work_a','work_b']].max(axis=1)
 pc.to_csv(A/'figure1_component_savings.csv',index=False)
 for i,scene in enumerate(SCENES):
  vals=pc[pc.scene==scene].saving.to_numpy();axs[1].scatter(vals,np.repeat(i,len(vals))+np.random.default_rng(42+i).uniform(-.18,.18,len(vals)),s=8,color=COLORS[i],alpha=.4,edgecolors='none')
  if len(vals):axs[1].plot(np.median(vals),i,'|',color='black',markersize=16,markeredgewidth=1.5)
 axs[1].set_yticks(range(5),SN);axs[1].invert_yaxis();axs[1].set_xlim(0,1);axs[1].xaxis.set_major_formatter(PercentFormatter(1));axs[1].set_xlabel('Primary-component work reduction');axs[1].set_title('(b) Unequal primary components')
 fig.tight_layout(w_pad=2);finish(fig,'figure_1_correct_work_differences')
 at=read('attenuation_primary');at=at[at.difficulty=='medium'];fig,axs=plt.subplots(1,3,figsize=(7.1,2.9),sharex=True,sharey=True)
 shown=at[at.timing.isin(['online','online_without_admission','native_replay_4'])];ylo=min(-.05,float(shown.time_saving.min())-.05) if len(shown) else -.05;yhi=max(1.05,float(shown.time_saving.max())+.05) if len(shown) else 1.05;symlog=ylo < -2
 if symlog:ylo*=1.2
 for ax,timing,title in zip(axs,['online','online_without_admission','native_replay_4'],['Online','Online minus admission','Native replay: 4 workers']):
  t=at[at.timing==timing]
  for scene,color,label in zip(SCENES,COLORS,SN):
   if scene not in set(at.scene):continue
   x=t[t.scene==scene];ax.scatter(x.work_saving,x.time_saving,s=15,alpha=.65,c=color,edgecolors='white',linewidths=.25,label=label)
  ax.axhline(0,color='#555555',lw=.6);ax.plot([0,1],[0,1],'--',color='#555555',lw=.8);ax.set_xlim(0,1);ax.set_ylim(ylo,yhi)
  if symlog:ax.set_yscale('symlog',linthresh=1)
  ax.set_title(title+'\n'+str(len(t))+' pairs / '+str(t.parent.nunique())+' parents',fontsize=8);ax.set_xlabel('Work reduction');ax.xaxis.set_major_formatter(PercentFormatter(1));ax.yaxis.set_major_formatter(PercentFormatter(1));ax.grid(axis='y',zorder=0)
 if symlog:fig.text(.5,-.08,'Common y scale: signed-log beyond ±100%.',ha='center',fontsize=7)
 axs[0].set_ylabel('Time reduction');handles,labels=axs[0].get_legend_handles_labels();fig.legend(handles,labels,loc='lower center',ncol=5,frameon=False,fontsize=8,bbox_to_anchor=(.5,-.025));fig.tight_layout(w_pad=.7,rect=(0,.08,1,1));finish(fig,'figure_2_work_to_time')
 d=read('combined_main_stages');u=read('all_updates');fig,axs=plt.subplots(1,3,figsize=(7.1,4.5),sharey=True)
 for ax,cond,title in zip(axs,['base','related','unrelated'],['Initial validity','Relevant-change validity','Irrelevant-change validity']):
  t=d[d.condition==cond] if cond=='base' else u[(u.condition==cond)&u.base_G]
  vals=[];labels=[]
  for m in MODELS:
   g=t[t.model==m];vals.append(g.G.mean() if len(g) else 0);labels.append(f'{int(g.G.sum())}/{len(g)}' if len(g) else 'NA (0 eligible)')
  ax.barh(MN,vals,color=['#4267A8']*n_open+['#BA792B']*(len(MODELS)-n_open),height=.6)
  ax.axhline(n_open-.5,color='#b7bec5',lw=.6,ls='--')
  for i,(v,label) in enumerate(zip(vals,labels)):ax.text(min(v+.025,1.03),i,label,va='center',fontsize=7)
  ax.set_xlim(0,1.29);ax.set_xticks([0,.5,1]);ax.xaxis.set_major_formatter(PercentFormatter(1));ax.set_title(title,fontsize=9);ax.set_xlabel('All initial stages' if cond=='base' else 'Given a correct\ninitial stage')
 axs[0].invert_yaxis();fig.legend(handles=[Patch(color='#4267A8',label='Open-weight family API'),Patch(color='#BA792B',label='Closed API')],loc='lower center',ncol=2,frameon=False,fontsize=8,bbox_to_anchor=(.5,-.005));fig.tight_layout(w_pad=.7,rect=(0,.05,1,1));finish(fig,'figure_3_selective_adaptation')
 print('FIGURES_DONE')
if __name__=='__main__':main()
