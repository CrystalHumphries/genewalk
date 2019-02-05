"""This script creates a SIF file for a specific set of genes, based on a
pre-assembled network of interactions produced by INDRA. It loads the INDRA
interactions as a pandas DataFrame and, filters it to the genes of interest,
and adds some additional information before exporting as SIF."""
import pandas
import pickle
import argparse


def load_genes(fname):
    with open(fname, 'r') as fh:
        # Get the HGNC IDs from the list of genes file, assuming that
        # each line looks like HGNC:123
        genes = [l.strip().split(':')[1] for l in fh.readlines()]
    return genes


def load_indra_df(fname):
    with open(fname, 'rb') as fh:
        df = pickle.load(fh)
    return df


def dump_sif(df, fname):
    df.to_csv(fname)


def filter_to_genes(df, genes):
    # Look for pairs where both genes are in the gene list
    filters = ((df.agA_ns == 'HGNC') & (df.agA_id.isin(genes)))
    filters &= ((df.agB_ns == 'HGNC') & (df.agB_id.isin(genes)))
    # TODO: add further clauses to accept GO targets and relevant FPLX
    # sources/targets
    return df[filters]


def collapse_and_count(df):
    df_counts = df.groupby(by=['agA_ns', 'agA_id', 'agA_name',
                               'agB_ns', 'agB_id', 'agB_name',
                               'stmt_type']).sum()
    return df_counts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Choose a file with a list of genes to get a SIF for.')
    parser.add_argument('--genes', default='data/JQ1_HGNCidForINDRA.csv')
    parser.add_argument('--indra_df', default='data/stmt_df.pkl')
    parser.add_argument('--sif', default='data/JQ1_HGNCidForINDRA.sif')
    args = parser.parse_args()
    genes = load_genes(args.genes)
    df = load_indra_df(args.indra_df)
    df = filter_to_genes(df, genes)
    df = collapse_and_count(df)
    dump_sif(df, args.sif)