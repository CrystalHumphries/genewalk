import os
import copy
import logging
import argparse
import pandas as pd
import numpy as np
import pickle as pkl
import networkx as nx
import statsmodels.stats.multitest
from indra.databases import hgnc_client
from genewalk.get_indra_stmts import load_genes

logger = logging.getLogger('genewalk.perform_statistics')


class GeneWalk(object):
    """GeneWalk object that generates the final output list of significant GO
    terms for each gene in the input list with genes of interest from an
    experiment, for example differentially expressed genes or CRISPR screen
    hits.
    If an input gene is not in the output file, this could have the following
    reasons:
    1) No reaction statements could be retrieved from the data_source selected
    in get_node_vectors.py (Pathway Commons, indra or fromUser).
    2) No connected (annotated) GO terms are present in the GeneWalk Network.
    3) (In case of mouse genes) no mapped human ortholog was identified.
    4) (if alpha_FDR set to < 1) no annotated GO term were significant at the
    chosen significance level alpha_FDR.

    Parameters
    ----------
    fgenes : str or list
        Filename of input list with HGNC ids (or MGI ids) from genes of
        interest (default: gene_list.csv).
    mouse_genes : bool
        Set to True if the input list are MGI:IDs from mouse genes
        (default: False).

    Attributes
    ----------
    hgncid : list of str
        list of HGNC ids from genes of interest (loaded from fgenes in
        ase mouse_genes equals False)
    mdf : pandas.DataFrame
        pandas dataframe with MGI ids from genes of interest (loaded from
        fgenes in case mouse_genes equals True)
    graph : networkx.MultiGraph
        GeneWalk Network
    nv : dict
        node vectors (loaded from fnv_prefix and Nreps)
    srd : dict
        similarity random (null) distributions (loaded from fnull_dist)
    outdfs : list of pandas.DataFrame
        pandas DataFrames that will generate the final result of GeneWalk
    """

    # TODO: mouse gene mapping are loaded here to enable outputting the MGI
    #  IDs and symbols for mouse genes. This could be refactored to use INDRA's
    #  mappings and perhaps structured better in the code.
    def __init__(self, graph, genes, nvs, null_dist):
        '''
        if self.mouse_genes:
            self.mdf = pd.DataFrame()
            self._load_mouse_genes(fgenes)#read mgi csv into self.mdf and mapped HGNC:ID
        else:
            self.hgncid = load_genes(self.path+fgenes)#read hgnc list of
            # interest
        '''
        self.graph = graph
        self.GO_nodes = set(nx.get_node_attributes(self.graph, 'GO'))
        self.nv = []  # node vectors, defined in generate_output
        self.srd = null_dist
        self.outdfs = {}

    def _load_mouse_genes(self,fname):
        """Append human gene IDs to a df of mouse genes (self.mdf)."""
        self.mdf = pd.read_csv(self.path+fname)#assumes the csv has headers
        for c in self.mdf.columns:
            if c.startswith('MGI'):#assumes the first column starting with MGI is the relevant one with MGI:IDs
                self.mdf=self.mdf.rename(columns={c: 'MGI'})
                break
        mgi_ids = self.mdf['MGI']
        genes = []
        for mgi_id in mgi_ids:
            if mgi_id.startswith('MGI:'):
                mgi_id = mgi_id[4:]
            hgnc_id = hgnc_client.get_hgnc_from_mouse(mgi_id)
            if not hgnc_id:
                hgnc_id = 'NA'
            genes.append(hgnc_id)
        self.mdf.insert(loc=0,column='HGNC', value=pd.Series(genes, index=self.mdf.index))

    def generate_output(self, alpha_FDR=1):
        """Main function of GeneWalk object that generates the final output
        list

        Parameters
        ----------
        alpha_FDR
            significance level for FDR [0,1] (default=1, i.e. all GO
            terms are output). If set to a lower value, only annotated GO
            terms with mean padj < alpha_FDR are output.
        """
        if self.mouse_genes: 
            hgncid = list(self.mdf['HGNC'])
        else:  # human genes
            hgncid = self.hgncid
        # TODO: could this loop be parallelized or optimized?
        for rep in range(1, self.Nreps + 1):
            logger.info('%s/%s' % (rep, self.Nreps))

            # load node vectors
            fnv = 'GeneWalk_DW_nv_' + str(rep) + '.pkl'
            with open(self.path+fnv, 'rb') as f:
                self.nv = pkl.load(f)
            g_view = nx.nodes(self.graph)

            # initialize GeneWalk output dataframe for each replicate run
            if self.mouse_genes: 
                COLUMNS=['MGI', 'Symbol', 'mapped HGNC', 'mapped Symbol',
                         'GO description', 'GO:ID', 'N_con(gene)', 'N_con(GO)',
                         'similarity', 'pval', 'padj']
            else:  # human genes
                COLUMNS=['HGNC', 'Symbol',
                         'GO description', 'GO:ID',
                         'N_con(gene)', 'N_con(GO)',
                         'similarity', 'pval', 'padj']
            self.outdfs[rep]=pd.DataFrame(columns=COLUMNS)

            if self.mouse_genes:
                for n in g_view:
                    try: 
                        if self.graph.node[n]['HGNC'] in hgncid:
                            hid=self.graph.node[n]['HGNC']
                            mgis=self.mdf[self.mdf['HGNC']==hid]['MGI'].unique()
                            symbols=self.mdf[self.mdf['HGNC']==hid]['Symbol'].unique()
                            N_gene_con=len(self.graph[n])
                            for i in range(len(mgis)):
                                # TODO: refactor this to use a Python
                                #  datastructure to build up the results and
                                #  then in the end dump it into a data frame.
                                GOdf=self.get_GO_df(n,N_gene_con,alpha_FDR)
                                GOdf.insert(loc=0,column='MGI', 
                                            value=pd.Series(mgis[i], index=GOdf.index))
                                GOdf.insert(loc=1,column='Symbol', 
                                            value=pd.Series(symbols[i], index=GOdf.index))
                                GOdf.insert(loc=2,column='mapped HGNC', 
                                            value=pd.Series(hid, index=GOdf.index))
                                GOdf.insert(loc=3,column='mapped Symbol', value=pd.Series(n, index=GOdf.index))
                                GOdf.insert(loc=6,column='N_con(gene)', value=pd.Series(N_gene_con, index=GOdf.index))
                                self.outdfs[rep]=self.outdfs[rep].append(GOdf, ignore_index=True)
                    except KeyError:
                        pass
                self.outdfs[rep]['MGI'] = self.outdfs[rep]['MGI'].astype("category")
                self.outdfs[rep]['MGI'].cat.set_categories(self.mdf['MGI'].unique(), inplace=True)
                self.outdfs[rep]=self.outdfs[rep].sort_values(by=['MGI','mapped HGNC','mapped Symbol','GO:ID'])
            else:#human genes
                for n in g_view:
                    try: 
                        if self.graph.node[n]['HGNC'] in hgncid:
                            N_gene_con=len(self.graph[n])
                            GOdf=self.get_GO_df(n,N_gene_con,alpha_FDR)
                            GOdf.insert(loc=0,column='HGNC', value=pd.Series(self.graph.node[n]['HGNC'],
                                                                                index=GOdf.index))
                            GOdf.insert(loc=1,column='Symbol', value=pd.Series(n, index=GOdf.index))
                            GOdf.insert(loc=4,column='N_con(gene)', value=pd.Series(N_gene_con,index=GOdf.index))
                            self.outdfs[rep]=self.outdfs[rep].append(GOdf, ignore_index=True)
                    except KeyError:
                        pass
                self.outdfs[rep]['HGNC'] = self.outdfs[rep]['HGNC'].astype("category")
                self.outdfs[rep]['HGNC'].cat.set_categories(pd.Series(self.hgncid).unique(), inplace=True)
                self.outdfs[rep]=self.outdfs[rep].sort_values(by=['HGNC','Symbol','GO:ID'])

            mppr={'similarity':str(rep)+':similarity','pval':str(rep)+':pval','padj':str(rep)+':padj'}
            self.outdfs[rep]=self.outdfs[rep].rename(mapper=mppr,axis=1)
        #Merge all self.Nrep experimentals to calculate mean and sem statistics
        self.outdfs[self.Nreps+1]=copy.deepcopy(self.outdfs[1])
        for rep in range(2,self.Nreps+1):
            if self.mouse_genes: 
                COLUMNS=['MGI','Symbol','mapped HGNC','mapped Symbol',
                        'GO description','GO:ID',
                        'N_con(gene)','N_con(GO)']
            else:#human genes
                COLUMNS=['HGNC','Symbol',
                        'GO description','GO:ID',
                        'N_con(gene)','N_con(GO)']
            self.outdfs[self.Nreps+1]=self.outdfs[self.Nreps+1].merge(self.outdfs[rep],on=COLUMNS,how='outer')
        self.outdfs[self.Nreps+1].insert(loc=len(COLUMNS),column='mean:sim',
                    value=self.outdfs[self.Nreps+1][[str(r)+':similarity' for r in range(1,self.Nreps+1)]].mean(axis=1))
        self.outdfs[self.Nreps+1].insert(loc=len(COLUMNS)+1,column='sem:sim',
                    value=self.outdfs[self.Nreps+1][[str(r)+':similarity' for r in \
                                                          range(1,self.Nreps+1)]].std(axis=1)/np.sqrt(self.Nreps))
        self.outdfs[self.Nreps+1].insert(loc=len(COLUMNS)+2,column='mean:pval',
                    value=self.outdfs[self.Nreps+1][[str(r)+':pval' for r in range(1,self.Nreps+1)]].mean(axis=1))
        self.outdfs[self.Nreps+1].insert(loc=len(COLUMNS)+3,column='sem:pval',
                    value=self.outdfs[self.Nreps+1][[str(r)+':pval' for r in \
                                                          range(1,self.Nreps+1)]].std(axis=1)/np.sqrt(self.Nreps))
        self.outdfs[self.Nreps+1].insert(loc=len(COLUMNS)+4,column='mean:padj',
                    value=self.outdfs[self.Nreps+1][[str(r)+':padj' for r in range(1,self.Nreps+1)]].mean(axis=1))
        self.outdfs[self.Nreps+1].insert(loc=len(COLUMNS)+5,column='sem:padj',
                    value=self.outdfs[self.Nreps+1][[str(r)+':padj' for r in \
                                                          range(1,self.Nreps+1)]].std(axis=1)/np.sqrt(self.Nreps))   
        if self.mouse_genes:
            self.outdfs[self.Nreps+1]['MGI'] = self.outdfs[self.Nreps+1]['MGI'].astype("category")
            self.outdfs[self.Nreps+1]['MGI'].cat.set_categories(self.mdf['MGI'].unique(), inplace=True)
            self.outdfs[self.Nreps+1]=self.outdfs[self.Nreps+1].sort_values(by=['MGI','Symbol',
                                                                                'mean:padj','GO description'])
        else:#human genes
            self.outdfs[self.Nreps+1]['HGNC'] = self.outdfs[self.Nreps+1]['HGNC'].astype("category")
            self.outdfs[self.Nreps+1]['HGNC'].cat.set_categories(pd.Series(self.hgncid).unique(), inplace=True)
            self.outdfs[self.Nreps+1]=self.outdfs[self.Nreps+1].sort_values(by=['HGNC','mean:padj','GO description'])    
        self.outdfs[self.Nreps+1]=self.outdfs[self.Nreps+1].drop([str(r)+':similarity' for r in range(1,self.Nreps+1)],axis=1)
        self.outdfs[self.Nreps+1]=self.outdfs[self.Nreps+1].drop([str(r)+':pval' for r in range(1,self.Nreps+1)],axis=1)
        self.outdfs[self.Nreps+1]=self.outdfs[self.Nreps+1].drop([str(r)+':padj' for r in range(1,self.Nreps+1)],axis=1)
        self.outdfs[self.Nreps+1].to_csv(self.path+fname_out, index=False)
        return self.outdfs[self.Nreps+1]

    def P_sim(self, sim, N_con):
        # Gets the p-value by comparing the experimental similarity value
        # to the null distribution.
        # TODO: is searchsorted the slow step here?
        dist_key = 'd'+str(np.floor(np.log2(N_con)))
        RANK = np.searchsorted(self.srd[dist_key], sim, side='left',
                               sorter=None)
        PCT_RANK = float(RANK)/len(self.srd[dist_key])
        pval = 1-PCT_RANK
        return pval

    def get_GO_df(self, geneoi, N_gene_con, alpha_FDR):
        N_GO_CON = []
        PVAL = []
        FDR = []
        DES = []
        GO_con2gene = set(self.graph[geneoi]).intersection(self.GO_nodes)
        simdf = pd.DataFrame(self.nv.most_similar(geneoi,
                                                  topn=len(self.nv.vocab)),
                             columns=['GO:ID','similarity'])
        simdf=simdf[simdf['GO:ID'].isin(GO_con2gene)]

        for i in simdf.index:
            N_GO_con = len(self.graph[simdf['GO:ID'][i]])
            N_GO_CON.append(N_GO_con)
            DES.append(self.graph.node[simdf['GO:ID'][i]]['name'])
            pval = self.P_sim(simdf['similarity'][i],min(N_GO_con,N_gene_con))
            PVAL.append(pval)
        simdf.insert(loc=0,column='GO description',
                     value=pd.Series(DES, index=simdf.index))
        simdf.insert(loc=2,column='N_con(GO)',
                     value=pd.Series(N_GO_CON, index=simdf.index))
        simdf.insert(loc=4,column='pval',
                     value=pd.Series(PVAL, index=simdf.index))
        BOOL,q_val = \
            statsmodels.stats.multitest.fdrcorrection(simdf['pval'],
                                                      alpha=alpha_FDR,
                                                      method='indep')
        simdf.insert(loc=5, column='padj',
                     value=pd.Series(q_val, index=simdf.index))
        if alpha_FDR < 1:
            return simdf[simdf['padj'] < alpha_FDR]
        else:
            return simdf


if __name__ == '__main__':
    # Handle command line arguments
    # TODO: implement CLI with documentation here
    parser = argparse.ArgumentParser(
        description='Choose a path to the gene list.')
    parser.add_argument('--path', default='~/genewalk/')
    parser.add_argument('--genes', default='gene_list.csv')
    parser.add_argument('--alpha_FDR', default=1)
    parser.add_argument('--mouse_genes',default=False)
    parser.add_argument('--filename_out',default='GeneWalk.csv')
    args = parser.parse_args()
    log_handler = logging.FileHandler(os.path.join(args.path, 'LogErr',
                                                   '%s.log' % logger.name))
    logger.addHandler(log_handler)
    GW = GeneWalk(path=args.path, fgenes=args.genes,
                  mouse_genes=args.mouse_genes)
    GW.generate_output(alpha_FDR=args.alpha_FDR, fname_out=args.filename_out)
