## def aggregate_interaction_clusters(...):

    """
    Analys av lokala interaktionskluster per optisk yta.

    Denna funktion grupperar ray-träffar efter:
        (object_name, bounce_index, prev_hit_label)

    => Ett kluster representerar:
       "Alla strålar som träffar samma objekt, vid samma bounce,
        och som kommer från samma föregående yta."

    ⚠️ Notera:
        - last_hit_label används endast som metadata
        - kluster skapas INTE baserat på vilken yta på objektet som träffas

    --------------------------------------------------
    INPUT
    --------------------------------------------------
    mode : str
        Vilken ray-typ som ska analyseras ("final", etc.)

    min_hits : int
        Minsta antal träffar för att ett kluster ska inkluderas

    --------------------------------------------------
    OUTPUT
    --------------------------------------------------
    dict: {cluster_id -> cluster_data}

    Varje kluster innehåller:

    CORE:
        object               : objektets namn
        bounce               : bounce-index
        prev_hit_label       : föregående yta
        last_hit_labels      : vilka ytor som faktiskt träffades
        hit_count            : antal träffar
        points               : numpy-array med 3D-punkter

    POWER:
        power.in             : total inkommande energi
        power.out            : total utgående energi
        power.absorbed       : absorberad energi
        power.efficiency     : out / in

    POSITION:
        centroid[3D, XY, XZ, YZ]

    SPREAD:
        radius (RMS)
        radius_max
        covariance-matriser

    METRICS:
        density              : punktdensitet (ej normaliserad)
        roundness            : form (0 = linje, 1 = cirkulär)

    --------------------------------------------------
    ANVÄNDNING
    --------------------------------------------------
    - Identifiera hotspots
    - Utvärdera optisk fokusering
    - Mät hur tight strålar träffar en yta
    - Förlustanalys (absorbed power)

    --------------------------------------------------
    TOLKNING
    --------------------------------------------------
    Hög density  -> koncentrerad träffbild
    Hög roundness -> symmetrisk spot
    Låg roundness -> linjeformad / astigmatisk fördelning

    Detta är en LOKAL analys (per interaktion).
    """

## def debug_print_surface_clusters(...):

    """
    Debug-utskrift av klusterstruktur som ASCII-träd.

    Visualiserar hierarkin:
        object → bounce → prev_hit_label → cluster

    --------------------------------------------------
    SYFTE
    --------------------------------------------------
    - Snabb inspektion av hur kluster bildas
    - Verifiera grouping-logik
    - Se spridning av träffar per interaktion

    --------------------------------------------------
    INPUT
    --------------------------------------------------
    plane : str
        Visningsplan ("XY", "XZ", "YZ")

    mode : str
        Ray-mode

    min_hits : int
        Filtrering av små kluster

    max_points_preview : int
        Hur många punkter som ska skrivas per kluster

    --------------------------------------------------
    OUTPUT
    --------------------------------------------------
    Skriver till konsol:

    - Objekt
    - Bounce
    - Föregående yta
    - Kluster ID
    - Hit count
    - Radius
    - Centroid
    - Exempelpunkter

    --------------------------------------------------
    ANVÄNDNING
    --------------------------------------------------
    - Debug av optisk pipeline
    - Förstå hur rays grupperas
    - Identifiera oväntade bounce-paths
    """

## def aggregate_path_statistics(...):

    """
    Aggrerar statistik per optisk strålgång (path).

    Gruppnyckel:
        (emitter_id, path_signature)

    path_signature:
        Sekvens av (object_name, last_hit_label)

    => Representerar en exakt optisk väg genom systemet.

    --------------------------------------------------
    INPUT
    --------------------------------------------------
    mode : str
        Ray-typ

    min_bounce, max_bounce : int
        Begränsa vilka interaktioner som inkluderas

    hit_selection : str
        "incoming"  -> första träffen
        "outgoing"  -> sista träffen
        "all"       -> första + sista (default)

    --------------------------------------------------
    OUTPUT
    --------------------------------------------------
    hit_records : list
        Platt lista av alla träffar

    path_stats : dict
        { (emitter_id, path_signature) -> data }

    DATA PER PATH:
        centroid
        count
        power_in / power_out / absorbed_power
        min / max / mean bounce
        points

    --------------------------------------------------
    ANVÄNDNING
    --------------------------------------------------
    - Identifiera dominerande optiska paths
    - Energiflöde genom systemet
    - Förlustanalys på path-nivå
    - Klassificera strålgångar

    --------------------------------------------------
    NOTERA
    --------------------------------------------------
    Detta är en GLOBAL analys (hela rays),
    inte lokala träffpunkter som i cluster-analysen.
    """

## def collect_ray_hits_and_stats(...):

    """
    Kärnfunktion för att extrahera ray-data + path-statistik.

    Returnerar både:
        - individuella träffar (hits)
        - aggregerad statistik per optisk path

    --------------------------------------------------
    INPUT
    --------------------------------------------------
    mode : str
        Vilka rays som inkluderas

    min_bounce, max_bounce :
        Filter på bounce-index

    hit_selection :
        "incoming"  -> första träffen per ray
        "outgoing"  -> sista träffen per ray
        "all"       -> första + sista (default)

    --------------------------------------------------
    OUTPUT
    --------------------------------------------------
    hits : list
        Lista av alla individuella träffar med:

        - objekt
        - labels
        - position
        - power (in/out/absorbed)
        - distances

    stats : dict
        Grupperad statistik per (emitter, path):

        centroid
        count
        power
        length:
            sum          -> total sträcklängd
            mean         -> medel per ray
            mean_final   -> slutlig längd
        bounce-statistik
        hit_points

    --------------------------------------------------
    ANVÄNDNING
    --------------------------------------------------
    - Bas för ALL vidare analys
    - Input till visualisering
    - Bygga egna metrics (density, fokus etc.)
    - Diagnostik av rays

    --------------------------------------------------
    STRUKTURELL SKILLNAD
    --------------------------------------------------
    Hits:
        Enskilda fysikaliska interaktioner

    Stats:
        Sammanfattning av hela strålgångar

    --------------------------------------------------
    VIKTIGT
    --------------------------------------------------
    Detta är den mest generella funktionen i modulen.
    Andra analyser (clusters etc.) bygger på liknande data,
    men med annan gruppering.
    """

``

## def analyze_rays(mode="final"):

    """
    Enkel wrapper för att hämta ray-analys.

    Returnerar:
        {
            "hits":  lista av träffar,
            "stats": path-baserad statistik
        }

    --------------------------------------------------
    SYFTE
    --------------------------------------------------
    - Bakåtkompatibilitet med äldre API
    - Snabb access till standardanalys

    --------------------------------------------------
    ANVÄNDNING
    --------------------------------------------------
    result = analyze_rays()

    hits = result["hits"]
    stats = result["stats"]
    """

justera så att det är i markdown
