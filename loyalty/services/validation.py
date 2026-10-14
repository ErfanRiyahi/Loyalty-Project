"""Label-free k=3 diagnostics. These metrics do not measure future churn accuracy."""
import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import (
    silhouette_samples, davies_bouldin_score, calinski_harabasz_score,
    adjusted_rand_score,
)


def validate_clusters(X, labels, label_names, run_stability=True):
    X = np.asarray(X, dtype=float)
    labels = np.asarray(labels)
    n = len(labels)
    unique, counts = np.unique(labels, return_counts=True)
    if not np.isfinite(X).all():
        raise ValueError('Clustering features must be finite.')
    rng = np.random.default_rng(42)
    sample = np.sort(rng.choice(n, size=min(n, 2000), replace=False))
    sample_labels = labels[sample]
    sample_unique = np.unique(sample_labels)
    silhouette = None
    values = None
    warnings = []
    if 1 < len(unique) < n:
        db = float(davies_bouldin_score(X, labels))
        ch = float(calinski_harabasz_score(X, labels))
    else:
        db = ch = None
        warnings.append('Internal separation metrics need more customers than clusters.')
    if len(sample_unique) == len(unique) and 1 < len(sample_unique) < len(sample):
        # Distances are evaluated within this uniform sample, not against all rows.
        values = silhouette_samples(X[sample], sample_labels)
        silhouette = float(values.mean())
    elif n > len(sample):
        warnings.append('The uniform silhouette sample omitted a cluster; silhouette is unavailable.')
    profile = []
    for cluster, count in zip(unique, counts):
        selected = sample_labels == cluster
        profile.append({
            'cluster': int(cluster), 'label': label_names[int(cluster)],
            'count': int(count), 'share': float(count / n),
            'silhouette_sample_count': int(selected.sum()),
            'mean_silhouette': float(values[selected].mean()) if values is not None and selected.any() else None,
            'negative_silhouette_share': float((values[selected] < 0).mean()) if values is not None and selected.any() else None,
        })
    if counts.min() / n < .01:
        warnings.append('One cluster has fewer than 1% of clustered customers; inspect its profile.')
    stability = {
        'status': 'disabled' if not run_stability else 'unavailable',
        'method': 'Subsample refits, fixed preprocessing, ARI against the main partition',
        'requested_runs': 5 if run_stability else 0,
        'successful_runs': 0, 'train_rows': 0, 'evaluation_rows': len(sample),
        'ari_mean': None, 'ari_min': None, 'ari_std': None, 'runs': [],
        'note': 'In-sample robustness diagnostic, not held-out churn accuracy; preprocessing is kept fixed.',
    }
    if run_stability and n >= 10:
        train_size = min(10000, int(.8 * n))
        stability['train_rows'] = train_size
        for seed in [101, 102, 103, 104, 105]:
            train = np.random.default_rng(seed).choice(n, train_size, replace=False)
            if np.unique(X[train], axis=0).shape[0] < 3:
                stability['runs'].append({'seed': seed, 'ari': None, 'reason': 'Fewer than 3 distinct training vectors'})
                continue
            fitted = KMeans(n_clusters=3, n_init=10, random_state=seed).fit(X[train])
            predictions = fitted.predict(X[sample])
            if len(np.unique(predictions)) < 3:
                stability['runs'].append({'seed': seed, 'ari': None, 'reason': 'Refit represents fewer than 3 clusters on evaluation sample'})
                continue
            stability['runs'].append({'seed': seed, 'ari': float(adjusted_rand_score(sample_labels, predictions))})
        scores = [item['ari'] for item in stability['runs'] if item['ari'] is not None]
        stability['successful_runs'] = len(scores)
        if scores:
            stability.update(status='complete' if len(scores) == 5 else 'partial',
                             ari_mean=float(np.mean(scores)), ari_min=float(np.min(scores)), ari_std=float(np.std(scores)))
        if len(scores) < 5:
            warnings.append('Some stability refits could not represent three clusters; inspect skipped-run reasons.')
    elif run_stability:
        stability['note'] = 'At least 10 clustered customers are required for the subsample diagnostic.'
    return {
        'k': 3, 'n_clustered': n, 'n_features': X.shape[1],
        'silhouette': silhouette, 'davies_bouldin': db, 'calinski_harabasz': ch,
        'silhouette_sample_size': len(sample), 'silhouette_population_size': n,
        'silhouette_method': 'All clustered rows' if n == len(sample) else 'Uniform sample, at most 2000 rows, seed 42; distances within sample',
        'negative_silhouette_share': float((values < 0).mean()) if values is not None else None,
        'cluster_sizes': profile, 'stability': stability, 'warnings': warnings,
        'external_validation': {'status': 'not_available', 'reason': 'Independent true labels were not supplied. A confusion matrix and churn accuracy cannot be computed.'},
    }
