from pathlib import Path
import json
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
R=Path(__file__).resolve().parents[1];D=R/'data';P=R/'paper';F=R/'figures'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'svg.fonttype':'none','pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False})
models=['deepseek','kimi','qwen','gemma','glm','minimax','gemini','gemini37','grok','luna']
names=['DeepSeek V4 Pro 0813','Kimi K2.6','Qwen3.8 Flash','Gemma 4 31B','GLM-5.3 Flash','MiniMax M3','Gemini 3.8 Flash','Gemini 3.7 Flash','Grok 4.3','GPT-6 Luna']
d=pd.read_csv(D/'combined_main_stages.csv');s=pd.read_csv(D/'model_summary.csv').set_index('model');scenes=['graph','code_review','analytics','incident','appworld']
lines=[r'\begin{table*}[t]',r'\centering\small\setlength{\tabcolsep}{5pt}',r'\begin{tabular}{lrrrrrrr}',r'\toprule',r'Model & Graph & Code & SQL & Telemetry & Business & All stages & Initial \\',r'\midrule',r'\multicolumn{8}{l}{\emph{Open-weight model families, served through APIs}}\\']
for i,m in enumerate(models):
 if i==6:lines +=[r'\midrule',r'\multicolumn{8}{l}{\emph{Closed-model APIs}}\\']
 t=d[d.model.eq(m)];vals=[f'{t[t.scene.eq(scene)].G.mean()*100:.1f}' for scene in scenes];row=s.loc[m]
 vals +=[f'{row.valid/6:.1f}',f'{row.base_valid/2:.1f}']
 if m=='luna':vals[-2]=r'\textbf{'+vals[-2]+'}'
 if m=='gemini37':vals[-1]=r'\textbf{'+vals[-1]+'}'
 lines +=[names[i]+' & '+' & '.join(vals)+r' \\']
lines +=[r'\bottomrule',r'\end{tabular}',r'\caption{Joint-valid rates (\%). Each scenario column includes 120 stages per model; all stages includes 600, and initial includes 200. The balanced design makes the all-stage rate equal to the equal-scenario macro mean. Bold marks the best all-stage and initial rates. Endpoint-family grouping is descriptive: the Qwen production API is not identified with a specific released checkpoint.}',r'\label{tab:quality}',r'\end{table*}']
(P/'quality_table.tex').write_text('\n'.join(lines),encoding='utf-8')
lines=[r'\begin{table*}[t]',r'\centering\small\setlength{\tabcolsep}{5pt}',r'\begin{tabular}{lrrrrrr}',r'\toprule',r'Model & Submitted & $Q_1$ & $\G$ & Initial $\G$ & Related $\G$ & Irrelevant $\G$ \\',r'\midrule']
for m,n in zip(models,names):
 x=s.loc[m];lines +=[n+' & '+' & '.join([f'{int(x.submitted)}/600',f'{int(x.answer_valid)}/600',f'{int(x.valid)}/600',f'{int(x.base_valid)}/200',f'{int(x.related_valid)}/{int(x.related_n)}',f'{int(x.unrelated_valid)}/{int(x.unrelated_n)}'])+r' \\']
lines +=[r'\bottomrule\end{tabular}',r'\caption{Exact denominators. Submitted denotes an evaluated final submission. The final two columns require a valid initial stage. They are not the unconditional counts for the corresponding 200 update stages.}',r'\label{tab:counts}\end{table*}']
(P/'exact_counts.tex').write_text('\n'.join(lines),encoding='utf-8')
table=pd.DataFrame([dict(model=n,**s.loc[m].to_dict()) for m,n in zip(models,names)]);table.to_csv(D/'paper_model_counts.csv',index=False)
# Dataset diagram: each dataflow step occupies its own row and fixed grid.
fig,ax=plt.subplots(figsize=(11.6,3.8));ax.set(xlim=(0,12),ylim=(0,4));ax.axis('off')
cols=['#31688e','#21918c','#5c6caf','#c38331','#9b4f6c']
heads=['Graph retrieval','Code review','SQL analytics','Telemetry diagnosis','Business operations']
sources=['STaRK MAG\n4 graph clusters','4 Python packages\nseeded + clean revisions','BIRD × 2\nChinook + Northwind','RCAEval\n4 incident clusters','AppWorld exports\n4 task snapshots']
acts=['Filter, aggregate,\nfollow references','Read, probe, compare\ncase + version','Scope objects, join,\nbatch aggregates','Choose modalities,\naggregate windows','Read, reuse, update\nprotected state']
for i,(h,src,act,c) in enumerate(zip(heads,sources,acts,cols)):
 x=.1+i*2.4
 ax.add_patch(FancyBboxPatch((x,2.45),2.2,1.1,boxstyle='round,pad=.05',ec=c,fc=c+'12'))
 ax.text(x+1.1,3.28,h,ha='center',weight='bold',color=c,fontsize=9)
 ax.text(x+1.1,2.85,src,ha='center',va='center',fontsize=8.5)
 ax.text(x+1.1,2.12,act,ha='center',va='center',fontsize=8.5)
 ax.annotate('',xy=(x+1.1,1.49),xytext=(x+1.1,1.86),arrowprops={'arrowstyle':'->','color':c})
 ax.text(x+1.1,1.28,'20 parents\n5 easy + 15 medium',ha='center',va='center',fontsize=9,weight='bold')
ax.plot([.25,11.75],[.84,.84],color='#c6c6c6',lw=.8)
ax.text(6,.50,'Each parent: BASE  →  same checkpoint  →  RELEVANT / IRRELEVANT CHANGE',ha='center',weight='bold',fontsize=9.5)
ax.text(6,.08,'100 parents × 3 conditions × 2 repeats × 10 models = 6,000 stages',ha='center',fontsize=10)
fig.tight_layout(pad=.4)
for ext in ['pdf','svg','png']:fig.savefig(F/f'figure_4_dataset.{ext}',dpi=220,bbox_inches='tight')
plt.close(fig)
# Descriptive leaderboard is the validity gate only; no composite quality-efficiency score.
fig,axes=plt.subplots(1,2,figsize=(10.4,3.55),gridspec_kw={'width_ratios':[1.25,1]})
for ax,group,color in [(axes[0],models[:6],'#386cb0'),(axes[1],models[6:],'#c87a2c')]:
 group=sorted(group,key=lambda m:s.loc[m,'valid'],reverse=True)
 v=[100*s.loc[m,'valid']/600 for m in group];yy=np.arange(len(group))
 ax.barh(yy,v,color=color,height=.62)
 ax.set_yticks(yy,[names[models.index(m)] for m in group],fontsize=8.5);ax.invert_yaxis();ax.set_xlim(0,106)
 for y,a,m in zip(yy,v,group):ax.text(a+1,y,f'{a:.1f}',va='center',fontsize=8)
 ax.set_xlabel('Joint-valid stages (%)');ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True)
 axes[0].set_title('Open-weight family APIs',loc='left',weight='bold');axes[1].set_title('Closed APIs',loc='left',weight='bold')
fig.tight_layout()
for ext in ['pdf','svg','png']:fig.savefig(F/f'figure_5_validity.{ext}',dpi=220,bbox_inches='tight')
plt.close(fig)
print('Tables and 2 editable figures built')
