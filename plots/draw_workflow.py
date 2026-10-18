"""Vector drawing primitives; copied into each independent project generator."""
import argparse
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon, Circle, FancyArrowPatch

plt.rcParams.update({'font.family':'STIXGeneral', 'mathtext.fontset':'stix',
                     'font.size':9, 'pdf.fonttype':42, 'ps.fonttype':42,
                     'text.usetex':False, 'axes.unicode_minus':False})
CM = 1 / 2.54

class Drawing:
    def __init__(self, bounds):
        x0,y0,x1,y1 = bounds
        self.fig = plt.figure(figsize=((x1-x0)*CM,(y1-y0)*CM))
        self.ax = self.fig.add_axes([0,0,1,1], xlim=(x0,x1), ylim=(y0,y1))
        self.ax.set_aspect('equal'); self.ax.axis('off')
        self.nodes = {}
        self.labels = []

    def text(self,x,y,label,size=9,ha='center',va='center'):
        artist=self.ax.text(x,y,label,fontsize=size,ha=ha,va=va,
                            linespacing=1.15,clip_on=False,zorder=4)
        self.labels.append([artist,None])
        return artist

    def box(self,name,x,y,w,h,label,dashed=False,shape='rect',size=9):
        style = {'edgecolor':'black','facecolor':'white','linewidth':.55,
                 'linestyle':(0,(4,3)) if dashed else 'solid', 'zorder':2}
        if shape == 'diamond':
            obj = Polygon([(x-w/2,y),(x,y+h/2),(x+w/2,y),(x,y-h/2)],**style)
        elif shape == 'circle': obj = Circle((x,y),w/2,**style)
        else: obj = Rectangle((x-w/2,y-h/2),w,h,**style)
        self.ax.add_patch(obj); self.text(x,y,label,size)
        self.labels[-1][1]=(x-w/2,y-h/2,x+w/2,y+h/2)
        self.nodes[name] = (x,y,w,h,shape)

    def point(self,name,side):
        x,y,w,h,_ = self.nodes[name]
        return {'n':(x,y+h/2),'s':(x,y-h/2),'e':(x+w/2,y),
                'w':(x-w/2,y),'nw':(x-w/2,y+h/2),
                'ne':(x+w/2,y+h/2),'c':(x,y)}[side]

    def line(self,points,dashed=False):
        xs,ys=zip(*points)
        self.ax.plot(xs,ys,color='black',linewidth=.55,
                     linestyle=(0,(4,3)) if dashed else 'solid',zorder=1)

    def arrow(self,p,q,dashed=False,via=()):
        points=[p,*via,q]
        if via:self.line(points[:-1],dashed)
        self.ax.add_patch(FancyArrowPatch(points[-2],points[-1],
                         arrowstyle='-|>',mutation_scale=7.5,linewidth=.55,
                         color='black',shrinkA=0,shrinkB=0,
                         linestyle=(0,(4,3)) if dashed else 'solid',zorder=1))

    def edge(self,a,b,sa='s',sb='n',**kwargs):
        self.arrow(self.point(a,sa),self.point(b,sb),**kwargs)

    def frame(self,x,y,w,h):
        self.ax.add_patch(Rectangle((x,y),w,h,fill=False,edgecolor='black',
                                   linewidth=.55,linestyle=(0,(4,3)),zorder=0))

    def save(self,out,name):
        # Fixed physical canvas: do not enlarge or rasterize the scientific figure.
        self.fig.canvas.draw()
        renderer=self.fig.canvas.get_renderer()
        x0,x1=self.ax.get_xlim();y0,y1=self.ax.get_ylim()
        for artist,node in self.labels:
            b=artist.get_window_extent(renderer).transformed(self.ax.transData.inverted())
            if b.x0<x0-.02 or b.x1>x1+.02 or b.y0<y0-.02 or b.y1>y1+.02:
                raise ValueError(name+': clipped label '+repr(artist.get_text()))
            if node and (b.x0<node[0]-.02 or b.x1>node[2]+.02 or b.y0<node[1]-.02 or b.y1>node[3]+.02):
                raise ValueError(name+': label exceeds node '+repr(artist.get_text()))
        self.fig.savefig(out/(name+'.pdf'),format='pdf',
                         metadata={'Creator':'Python Matplotlib','Producer':None,
                                   'CreationDate':None,'ModDate':None})
        plt.close(self.fig)







EDGES=[('policy','ledger'),('policy','capture'),('ledger','gates'),('capture','gates'),
       ('gates','predicates'),('predicates','pass'),('predicates','fail'),('predicates','inc')]
def workflow(out):
    d=Drawing((0,0,8.5,5.9))
    d.box('policy',4.25,5.3,8.15,.95,'Lifetime topology: execution, submission, combined\nor context-only segments; declared handoff relations',size=8)
    d.box('ledger',2.1,3.95,3.85,1.35,'Independent operation ledger\nsubmission; entry/exit;\noutcome; context',size=7.8)
    d.box('capture',6.4,3.95,3.85,1.35,'Telemetry capture\ncandidates; parent/link;\nintervals; status/events;\nend/export witnesses',size=7.8)
    d.box('gates',4.25,2.6,8.15,1.05,'Qualify evidence per predicate\nCandidates: drained, always-on capture\nIntervals: additionally eligible clocks',size=8)
    d.box('predicates',4.25,1.4,8.15,.85,'Evaluate eligible lifetime/topology and context predicates\nA qualified discrepancy takes priority over missing evidence',size=7.8)
    for n,x,lab in [('pass',1.43,'PASS\nall obligations met'),('fail',4.25,'FAIL\nqualified discrepancy'),('inc',7.07,'INCONCLUSIVE\nunresolved obligation')]:
        d.box(n,x,.35,2.65,.62,lab,size=7.1)
    for a,b in EDGES:
        if a == 'policy':
            # Two aligned ports keep the declaration paths out of the inter-box gap.
            x=d.nodes[b][0]
            d.arrow((x,d.point(a,'s')[1]),d.point(b,'n'))
        elif b == 'gates':
            # Preserve the two inputs as separate vertical entries into qualification.
            x=d.nodes[a][0]
            d.arrow(d.point(a,'s'),(x,d.point(b,'n')[1]))
        elif a == 'predicates':
            # A right-angle fan-out leaves arrowheads clear of the outcome labels.
            x=d.nodes[b][0]
            d.arrow(d.point(a,'s'),d.point(b,'n'),via=((4.25,.82),(x,.82)))
        else:
            d.edge(a,b)
    d.save(out,'workflow')
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True)
    out=p.parse_args().output_dir;out.mkdir(parents=True,exist_ok=True);workflow(out)
