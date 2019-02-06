"""This script creates a SIF file for a specific set of genes, based on a
pre-assembled network of interactions produced by INDRA. It loads the INDRA
interactions as a pandas DataFrame and, filters it to the genes of interest,
and adds some additional information before exporting as SIF."""
import pandas
import pickle
import logging
import argparse
from indra.util import batch_iter
from indra.sources import indra_db_rest
from indra.databases import hgnc_client
from indra.preassembler.hierarchy_manager import hierarchies


logger = logging.getLogger('ngf.make_indra_sif')


def load_genes(fname):
    """Return a list of genes IDs from a file with lines like HGNC:123."""
    with open(fname, 'r') as fh:
        # Get the HGNC IDs from the list of genes file, assuming that
        # each line looks like HGNC:123
        genes = [l.strip().split(':')[1] for l in fh.readlines()]
    logger.info('Loaded %d genes from %s' % (len(genes), fname))
    return genes


def load_indra_df(fname):
    """Return an INDRA Statement data frame from a pickle file."""
    with open(fname, 'rb') as fh:
        df = pickle.load(fh)
    logger.info('Loaded %d rows from %s' % (len(df), fname))
    return df


def dump_pickle(stmts, fname):
    """Dump a list of Statements into a picke file."""
    with open(fname, 'wb') as fh:
        pickle.dump(stmts, fh)
    logger.info('Dumped %d statements into %s' % (len(stmts), fname))


def filter_to_genes(df, genes, fplx_terms):
    """Filter a data frame of INDRA Statements given gene and FamPlex IDs."""
    # Look for sources that are in the gene list or whose families/complexes
    # are in the FamPlex term list
    source_filter = (((df.agA_ns == 'HGNC') & (df.agA_id.isin(genes))) |
                     ((df.agA_ns == 'FPLX') & (df.agA_id.isin(fplx_terms))))
    # Look for targets that are in the gene list or whose families/complexes
    # are in the FamPlex term list, or which are GO terms
    target_filter = (((df.agB_ns == 'HGNC') & (df.agB_id.isin(genes))) |
                     ((df.agB_ns == 'FPLX') & (df.agB_id.isin(fplx_terms))) |
                     (df.agB_ns == 'GO'))
    # sources/targets
    df = df[source_filter & target_filter]
    logger.info('Filtered data frame to %d rows.' % len(df))
    return df


def get_famplex_terms(genes):
    """Get a list of associated FamPlex IDs from a list of gene IDs."""
    eh = hierarchies['entity']
    all_parents = set()
    for hgnc_id in genes:
        hgnc_name = hgnc_client.get_hgnc_name(hgnc_id)
        gene_uri = eh.get_uri('HGNC', hgnc_name)
        parents = eh.get_parents(gene_uri)
        parent_ids = [eh.ns_id_from_uri(par_uri)[1] for par_uri in parents]
        all_parents |= set(parent_ids)
    fplx_terms = sorted(list(all_parents))
    logger.info('Found %d relevant FamPlex terms.' % (len(fplx_terms)))
    return fplx_terms


def download_statements(df):
    """Download the INDRA Statements corresponding to entries in a data frame.
    """
    from indra.sources.indra_db_rest.util import logger
    logger.setLevel(logging.ERROR)
    all_stmts = []
    for idx, group in enumerate(batch_iter(df.hash, 500)):
        logger.info('Getting statement batch %d' % idx)
        stmts = indra_db_rest.get_statements_by_hash(list(group))
        all_stmts += stmts
    return all_stmts


if __name__ == '__main__':
    # Handle command line arguments
    parser = argparse.ArgumentParser(
        description='Choose a file with a list of genes to get a SIF for.')
    parser.add_argument('--genes', default='data/JQ1_HGNCidForINDRA.csv')
    parser.add_argument('--indra_df', default='data/stmt_df.pkl')
    parser.add_argument('--pickle', default='data/JQ1_HGNCidForINDRA.pkl')
    args = parser.parse_args()
    # Load genes and get FamPlex terms
    genes = load_genes(args.genes)
    fplx_terms = get_famplex_terms(genes)
    # Load INDRA Statements in a flat data frame
    df = load_indra_df(args.indra_df)
    # Filter the data frame to relevant entities
    df = filter_to_genes(df, genes, fplx_terms)
    # Download the Statement corresponding to each row
    stmts = download_statements(df)
    # Dump the Statements into a pickle file
    dump_pickle(stmts, args.pickle)
