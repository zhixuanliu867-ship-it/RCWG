"""Editable vector description of the frozen design; no raster elements."""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch,FancyArrowPatch
R=Path(__file__).resolve().parents[1];F=R/'figures';F.mkdir(exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':8,'svg.fonttype':'none','pdf.fonttype':42})
fig,ax=plt.subplots(figsize=(7.1,3.1));ax.set_xlim(0,10);ax.set_ylim(0,5);ax.axis('off')
def box(x,y,w,h,text,color='#edf2fa'):
 ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.06,rounding_size=0.08',linewidth=.7,edgecolor='#506078',facecolor=color));ax.text(x+w/2,y+h/2,text,ha='center',va='center',fontsize=8)
def arrow(a,b,rad=0):ax.add_patch(FancyArrowPatch(a,b,arrowstyle='-|>',mutation_scale=10,linewidth=.8,color='#506078',connectionstyle=f'arc3,rad={rad}'))
box(.12,3.55,1.5,.85,'Task contract\n+ source snapshot','#f4f4f4');box(2.05,3.55,2.15,.85,'Model decision\ncreate / revise / dispatch');box(4.7,3.55,2.2,.85,'Fixed native workers\nexecute selected operations');box(7.45,3.55,2.35,.85,'Versioned observations\n+ recorded native work','#e7f3ee')
arrow((1.68,3.97),(2.02,3.97));arrow((4.28,3.97),(4.65,3.97));arrow((6.98,3.97),(7.4,3.97));arrow((8.2,3.5),(3.1,3.5),-.14);ax.text(5.65,2.82,'New observations inform the next decision',ha='center',fontsize=8,color='#344a68')
box(.12,1.1,2.75,1.05,'100 parents / 20 source clusters\n5 scenarios / 10 models\n25 easy + 75 medium parents','#f4f4f4')
box(3.35,1.23,1.65,.8,'Initial execution\n2 draws per model');box(5.65,1.9,1.9,.65,'Relevant change','#f9eee0');box(5.65,.55,1.9,.65,'Irrelevant change','#e7f3ee')
arrow((5.05,1.8),(5.6,2.2));arrow((5.05,1.45),(5.6,.9));ax.text(5.25,1.46,'fork',ha='center',fontsize=7)
box(8.03,.65,1.8,1.9,'Task validity\nNative work\nTime realization\nUpdate cost','#edf2fa');arrow((7.6,2.2),(7.98,1.9));arrow((7.6,.9),(7.98,1.1))
ax.text(5.0,.02,'6,000 stages; initial plans, revisions, and execution traces retained separately',ha='center',fontsize=8)
fig.tight_layout(pad=.3)
for ext in ['svg','pdf','png']:fig.savefig(F/f'figure_0_experiment_design.{ext}',bbox_inches='tight',dpi=220)
plt.close(fig)
print('DESIGN_VECTOR_DONE')
