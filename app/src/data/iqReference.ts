import raw from './iq-reference.generated.json';
import { dependencyRows, type IqComparison, type IqRelation } from '@/domain/iq';
import { IQ_DEPENDENCIES_DAX, IQ_DEPENDENCIES_GQL } from '@/services/iqQueries';

export const IQ_RELATIONS: readonly IqRelation[] = raw.relations;

export const IQ_REFERENCE: IqComparison = {
  mode: 'repository',
  fingerprint: raw.fingerprint,
  tabular: {
    rows: dependencyRows(raw.tabular),
    query: IQ_DEPENDENCIES_DAX,
    source: 'Explicit table lookups over the repository CSVs',
    capturedAt: '',
  },
  ontology: {
    rows: dependencyRows(raw.ontology),
    query: IQ_DEPENDENCIES_GQL,
    source: 'Local traversal of the repository ontology bindings',
    capturedAt: '',
  },
};
