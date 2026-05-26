import numpy as np
from sklearn.cluster import DBSCAN
import alphashape
from shapely.geometry import MultiPoint
from dataclasses import dataclass

@dataclass
class BoundingBox:
    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float

@dataclass
class Cluster:
    cluster_id: int
    packages: list[dict]
    centroid: dict          # {"lat": float, "lng": float}
    bounding_box: BoundingBox
    polygon: list[dict]     # concave hull vertices as [{"lat": float, "lng": float}, ...]

@dataclass
class ClusterResult:
    clusters: list[Cluster]
    outliers: list[dict]

def _compute_bounding_box(packages: list[dict]) -> BoundingBox:
    lats = [p["lat"] for p in packages]
    lngs = [p["lng"] for p in packages]

    return BoundingBox(
        min_lat=min(lats), max_lat=max(lats),
        min_lng=min(lngs), max_lng=max(lngs)
    )
    
def _build_polygon(packages: list[dict])->list[dict]:
    coords = [(p["lng"], p["lat"]) for p in packages]   # shapely uses (x, y) = (lng, lat)
    try:
        alpha = alphashape.optimizealpha(coords)
        shape = alphashape.alphashape(coords, alpha)
        if not shape.is_valid:
            shape = shape.buffer(0)
        if shape.is_valid and not shape.is_empty:
            return [{"lat": lat, "lng": lng} for lng, lat in shape.exterior.coords]
        
    except Exception:
        pass

    # Fallback: convex hull
    hull = MultiPoint(coords).convex_hull
    return [{"lat": lat, "lng": lng} for lng, lat in hull.exterior.coords]

def cluster_packages(
    packages: list[dict],
    eps: float = 0.015,
    min_samples: int = 30
) -> ClusterResult:
    if not packages:
        return ClusterResult(clusters=[], outliers=[])
    
    # 1. Extract coords as numpy array [[lat, lng], ...]
    coords = np.array([[pkg["lat"], pkg["lng"]] for pkg in packages])

    # 2. Run DBSCAN(eps=eps, min_samples=min_samples).fit(coords)
    clustering = DBSCAN(eps=eps, min_samples=min_samples).fit(coords)
    labels = clustering.labels_

    # 3. Separate packages by label: -1 is outliers, 0, 1, 2... are clusters
    outliers = []
    clusters_map = {}

    for label, pkg in zip(labels, packages):
        if label == -1:
            outliers.append(pkg)
        else:
            clusters_map.setdefault(label, []).append(pkg)

    # 4. For each cluster: compute centroid (mean lat/lng), bounding box, polygon
    final_clusters = []
    for cluster_id, cluster_packages in clusters_map.items():
        # Compute stats for the packages in this cluster group
        lats = [p["lat"] for p in cluster_packages]
        lngs = [p["lng"] for p in cluster_packages]
        centroid = {"lat": sum(lats)/len(lats), "lng": sum(lngs)/ len(lngs)}
        bbox = _compute_bounding_box(cluster_packages)
        polygon = _build_polygon(cluster_packages)

        
        # Create the Cluster dataclass instance and append to the final list
        cluster = Cluster(
            cluster_id=cluster_id,
            packages=cluster_packages,
            centroid=centroid,
            bounding_box=bbox,
            polygon=polygon
        )
        final_clusters.append(cluster)

    # 5. Return ClusterResult
    return ClusterResult(clusters=final_clusters, outliers=outliers)