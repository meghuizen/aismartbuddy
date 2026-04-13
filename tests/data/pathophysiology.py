"""Pathophysiology test data — chronic post-infectious immune-dysregulation state.

47 genes across 4 biological systems, 12 pathways, 12 biological processes,
6 cell types, 5 phenotypes, and ~112 relationships.
"""

# ── Gene CSV data (47 genes) ──────────────────────────────────────

GENE_SCHEMA = (
    "id INT64 PRIMARY KEY, name STRING, z_score DOUBLE, "
    "direction STRING, description STRING, system STRING"
)

GENE_CSV = """\
id,name,z_score,direction,description,system
1,MX1,-2.0,reduced,Antiviral effector blocks viral replication,interferon
2,OAS2,-1.8,reduced,Viral RNA degradation enzyme,interferon
3,RSAD2,-1.9,reduced,Restricts viral budding (viperin),interferon
4,IFI6,-1.5,reduced,Interferon-stimulated gene anti-apoptotic,interferon
5,IFI27,-1.6,reduced,Interferon-stimulated gene,interferon
6,LY6E,-1.4,reduced,Blocks viral membrane fusion,interferon
7,DDX60,-1.3,reduced,Interferon-stimulated helicase,interferon
8,USP18,-1.7,reduced,ISG15 deconjugase IFN feedback,interferon
9,TLR3,-1.5,reduced,Viral dsRNA sensor,interferon
10,TAP2,-1.2,reduced,MHC-I antigen loading,interferon
11,IFNGR1,1.8,elevated,IFN-gamma receptor,interferon
12,JAK2,1.6,elevated,Cytokine signaling kinase,interferon
13,NLRX1,1.4,elevated,Inhibits RIG-I/MAVS antiviral pathway,interferon
14,IL6,2.98,elevated,Pro-inflammatory cytokine,inflammation
15,IL18,2.4,elevated,Inflammasome-activated cytokine,inflammation
16,C1S,1.3,elevated,Complement activation classical pathway,inflammation
17,MMP9,2.1,elevated,Neutrophil degranulation ECM degradation,inflammation
18,LTB4R,1.5,elevated,Leukotriene B4 receptor neutrophil chemotaxis,inflammation
19,KIT,1.4,elevated,Mast cell activation marker,inflammation
20,SIGLEC8,1.3,elevated,Mast cell eosinophil marker,inflammation
21,GATA3,-1.6,reduced,Th2 master regulator,inflammation
22,IKZF3,-1.4,reduced,Plasmablast differentiation,inflammation
23,IL21R,-1.3,reduced,Germinal center support receptor,inflammation
24,BACH2,-1.5,reduced,B-cell memory maintenance,inflammation
25,SLAMF6,-1.2,reduced,Adaptive immune signaling,inflammation
26,CCL5,-1.4,reduced,T-cell monocyte chemokine,inflammation
27,GZMK,-1.6,reduced,CD8 cytotoxic capacity granzyme K,inflammation
28,SLC2A1,-1.5,reduced,GLUT1 glucose transporter,metabolic
29,CPT1A,1.7,elevated,Fatty acid import to mitochondria rate-limiting,metabolic
30,HADHB,1.4,elevated,Beta-oxidation trifunctional protein,metabolic
31,PDHX,-1.6,reduced,Pyruvate dehydrogenase glycolysis-TCA link,metabolic
32,BCS1L,-1.3,reduced,Complex III assembly factor,metabolic
33,MT_ND3,-1.8,reduced,Complex I subunit,metabolic
34,TSFM,-1.4,reduced,Mitochondrial translation factor,metabolic
35,MTERF4,-1.3,reduced,Mitochondrial translation termination,metabolic
36,TFAM,1.5,elevated,Mitochondrial biogenesis compensatory,metabolic
37,TEFM,1.3,elevated,Mitochondrial transcription compensatory,metabolic
38,TK2,1.2,elevated,Mitochondrial dNTP synthesis compensatory,metabolic
39,COQ7,1.4,elevated,CoQ10 biosynthesis compensatory,metabolic
40,SMDT1,1.1,elevated,Mitochondrial calcium uniporter regulator,metabolic
41,OPTN,-1.2,reduced,Mitophagy receptor quality control,metabolic
42,S1PR1,-2.0,reduced,Lymphocyte egress from lymph nodes,neuroimmune
43,CCR5,-1.3,reduced,Effector T-cell homing to inflammation,neuroimmune
44,S1PR2,-1.1,reduced,Sphingosine signaling,neuroimmune
45,CLOCK,-1.5,reduced,Circadian master transcription factor,neuroimmune
46,DUSP1,1.6,elevated,Glucocorticoid-responsive MAPK phosphatase,neuroimmune
47,AVP,10.14,elevated,Vasopressin most deviant gene HPA axis,neuroimmune
48,PCSK2,1.8,elevated,ACTH-processing convertase,neuroimmune
49,OPRM1,-1.2,reduced,Mu-opioid receptor pain processing,neuroimmune
50,CACNA1A,-1.1,reduced,Calcium channel neurotransmission,neuroimmune"""

# ── Pathway CSV data (12 pathways) ────────────────────────────────

PATHWAY_SCHEMA = "id INT64 PRIMARY KEY, name STRING, category STRING, status STRING"

PATHWAY_CSV = """\
id,name,category,status
1,Interferon Antiviral Response,interferon,suppressed
2,Innate Inflammatory Activation,inflammation,active
3,Mitochondrial Energy Metabolism,metabolic,stressed
4,Neuroimmune-Endocrine Regulation,neuroimmune,dysregulated
5,ISG Effector Program,interferon,suppressed
6,IL-6/IL-18 Inflammasome Axis,inflammation,active
7,Adaptive Immune Response,inflammation,suppressed
8,Electron Transport Chain,metabolic,impaired
9,Mitochondrial Biogenesis,metabolic,compensatory
10,Fatty Acid Oxidation,metabolic,active
11,Lymphocyte Trafficking,neuroimmune,impaired
12,HPA Stress Axis,neuroimmune,activated"""

# ── BioProcess CSV data (12 processes) ────────────────────────────

BIOPROCESS_SCHEMA = "id INT64 PRIMARY KEY, name STRING, status STRING, description STRING"

BIOPROCESS_CSV = """\
id,name,status,description
1,Viral RNA Degradation,impaired,OAS2-mediated viral RNA cleavage
2,Viral Budding Restriction,impaired,RSAD2/viperin blocks viral egress
3,MHC-I Antigen Presentation,impaired,TAP2-dependent peptide loading
4,Neutrophil Degranulation,active,MMP9-mediated ECM degradation
5,Complement Activation,active,Classical pathway via C1S
6,Mast Cell Activation,active,KIT/SIGLEC8 driven expansion
7,Glycolysis,impaired,SLC2A1 reduced PDHX blocked
8,Beta-Oxidation,active,CPT1A/HADHB fatty acid utilization
9,Mitochondrial Quality Control,impaired,OPTN-dependent mitophagy offline
10,Circadian Immune Gating,impaired,CLOCK-dependent trafficking rhythms
11,Cortisol Signaling,active,DUSP1-mediated MAPK suppression
12,Lymphocyte Egress,impaired,S1PR1-dependent node exit"""

# ── CellType CSV data (6 cell types) ─────────────────────────────

CELLTYPE_SCHEMA = "id INT64 PRIMARY KEY, name STRING, activation_status STRING"

CELLTYPE_CSV = """\
id,name,activation_status
1,Neutrophil,activated
2,Mast Cell,activated
3,CD8 T Cell,exhausted
4,Th2 Cell,suppressed
5,B Cell,impaired
6,Plasmablast,suppressed"""

# ── Phenotype CSV data (5 phenotypes) ─────────────────────────────

PHENOTYPE_SCHEMA = "id INT64 PRIMARY KEY, name STRING, description STRING"

PHENOTYPE_CSV = """\
id,name,description
1,Impaired Antiviral Defense,Reduced ISG expression poor viral clearance
2,Chronic Systemic Inflammation,Persistent IL-6/IL-18 driven inflammation
3,Metabolic Exhaustion,Energy production failure with compensatory shift
4,Immune Cell Trafficking Defect,Poor lymphocyte homing and egress
5,Neuroendocrine Stress,HPA axis activation circadian disruption altered pain"""

# ── Relationship data ─────────────────────────────────────────────

# ParticipatesIn: Gene → Pathway (gene_id, pathway_id, role)
PARTICIPATES_IN_SCHEMA = "role STRING"
PARTICIPATES_IN_CSV = """\
from,to,role
1,1,ISG effector
1,5,ISG effector
2,1,ISG effector
2,5,ISG effector
3,1,ISG effector
3,5,ISG effector
4,1,ISG effector
4,5,ISG effector
5,1,ISG effector
5,5,ISG effector
6,1,ISG effector
6,5,ISG effector
7,1,ISG effector
7,5,ISG effector
8,1,ISG feedback
8,5,ISG feedback
9,1,sensor
10,1,antigen processing
11,1,receptor amplification
12,1,signaling kinase
13,1,cross-system inhibitor
13,3,cross-system link
14,2,cytokine driver
14,6,cytokine driver
15,2,inflammasome
15,6,inflammasome
16,2,complement
17,2,neutrophil effector
18,2,chemotaxis
19,2,mast cell marker
19,6,mast cell activation
20,2,mast cell marker
20,6,mast cell marker
21,2,adaptive regulator
21,7,Th2 master regulator
22,2,adaptive
22,7,plasmablast factor
23,2,adaptive
23,7,germinal center
24,2,adaptive
24,7,memory maintenance
25,2,adaptive
25,7,signaling
26,2,chemokine
26,7,T-cell recruitment
27,2,cytotoxic
27,7,CD8 effector
28,3,glucose uptake
28,8,substrate supply
31,3,TCA entry
31,8,pyruvate linkage
32,3,ETC assembly
32,8,Complex III
33,3,ETC subunit
33,8,Complex I
34,3,translation
34,8,ETC production
35,3,translation
35,8,ETC production
41,3,quality control
41,8,mitophagy
36,3,biogenesis
36,9,transcription factor
37,3,biogenesis
37,9,transcription
38,3,biogenesis
38,9,dNTP supply
39,3,biogenesis
39,9,CoQ synthesis
40,3,calcium handling
40,9,calcium regulation
29,3,fatty acid import
29,10,rate-limiting enzyme
30,3,beta-oxidation
30,10,trifunctional protein
42,4,trafficking
42,11,egress receptor
43,4,trafficking
43,11,homing receptor
44,4,trafficking
44,11,sphingosine signaling
45,4,circadian
45,11,circadian gating
46,4,HPA response
46,12,glucocorticoid
47,4,HPA drive
47,12,vasopressin
48,4,HPA processing
48,12,ACTH conversion
49,4,neurological
50,4,neurological"""

# Regulates: Gene → Gene (from_id, to_id, type)
REGULATES_SCHEMA = "type STRING"
REGULATES_CSV = """\
from,to,type
11,12,activates
12,1,activates
12,2,activates
13,1,inhibits
13,2,inhibits
13,3,inhibits
15,14,activates
14,17,activates
14,16,activates
46,21,inhibits
46,24,inhibits
45,42,activates
45,43,activates
47,48,activates
31,28,enables
32,33,assembles
34,33,translates
35,32,translates
18,17,amplifies
8,11,inhibits"""

# CompensatesFor: Gene → Gene (from_id, to_id, mechanism)
COMPENSATES_FOR_SCHEMA = "mechanism STRING"
COMPENSATES_FOR_CSV = """\
from,to,mechanism
29,28,fatty acid replaces glucose uptake
36,33,biogenesis replaces failed ETC
37,32,transcription compensates assembly failure
38,34,dNTP supply supports translation
39,32,CoQ biosynthesis aids ETC
40,41,calcium handling while mitophagy offline"""

# DrivesProcess: Gene → BioProcess (gene_id, process_id, mechanism)
DRIVES_PROCESS_SCHEMA = "mechanism STRING"
DRIVES_PROCESS_CSV = """\
from,to,mechanism
2,1,enzymatic RNA cleavage
3,2,membrane lipid disruption
10,3,peptide transport
17,4,matrix metalloproteinase
16,5,complement protease
19,6,receptor tyrosine kinase
28,7,glucose transport
29,8,fatty acid shuttling
41,9,mitophagy receptor
45,10,transcriptional regulation
46,11,phosphatase signaling
42,12,sphingosine receptor
31,7,pyruvate oxidation
20,6,cell surface receptor"""

# CellExpresses: CellType → Gene (cell_id, gene_id, context)
CELL_EXPRESSES_SCHEMA = "context STRING"
CELL_EXPRESSES_CSV = """\
from,to,context
1,17,degranulation product
1,18,chemotaxis receptor
2,19,activation marker
2,20,surface receptor
3,27,cytotoxic effector
3,26,chemokine production
4,21,master regulator
5,24,memory maintenance
5,23,germinal center receptor
6,22,differentiation factor"""

# PathwayInteracts: Pathway → Pathway (from_id, to_id, mechanism, direction)
PATHWAY_INTERACTS_SCHEMA = "mechanism STRING, direction STRING"
PATHWAY_INTERACTS_CSV = """\
from,to,mechanism,direction
1,2,NLRX1 suppresses antiviral while inflammation active,bidirectional
3,1,mitochondrial stress reduces antiviral signaling,causal
4,2,HPA axis suppresses adaptive immunity,causal
3,2,energy failure sustains inflammatory activation,causal
4,1,circadian disruption impairs immune timing,causal
3,4,metabolic stress drives neuroendocrine activation,causal"""

# ProducesPhenotype: Pathway → Phenotype (pathway_id, phenotype_id, confidence)
PRODUCES_PHENOTYPE_SCHEMA = "confidence STRING"
PRODUCES_PHENOTYPE_CSV = """\
from,to,confidence
1,1,high
2,2,high
3,3,high
4,4,high
4,5,high
11,4,moderate"""
