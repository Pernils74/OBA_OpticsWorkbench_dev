# oba_lens_materials.py

# Struktur: "Namn": (Brytningsindex n_d, Abbe-tal V_d)
# n_d avser d-linjen (587.6 nm)
# Abbe-tal: Högt = låg dispersion, Lågt = hög dispersion

MATERIAL_DATA_old = {
    # Name : () brytindex, Abbe - tal)
    # Custom → använd objektets egna värden
    "Custom": (None, None),
    # Optical glass
    "N-BK7": (1.5168, 64.17),
    "N-SF11": (1.7847, 25.76),
    "F2": (1.6200, 36.37),
    "SF2": (1.6477, 33.85),
    "Fused Silica": (1.4585, 67.8),
    # Kristaller
    "Sapphire": (1.7680, 72.2),
    "Zinc Selenide": (2.4030, 0.0),  # IR-material, ingen Abbe-modell här
    # Plast
    "Acrylic (PMMA)": (1.4910, 57.2),
    "Polycarbonate": (1.5850, 29.9),
    # Vätskor / Luft
    "Water": (1.3330, 55.7),
    "Air": (1.0003, 0.0),
}


MATERIAL_DATA = {
    # --------------------------------------------------
    # Custom → använd objektets egna värden
    # --------------------------------------------------
    "Custom": {
        "type": "custom",
        "n": None,
        "Vd": None,
    },
    # --------------------------------------------------
    # Optical glass (Sellmeier-data)
    # --------------------------------------------------
    "N-BK7": {
        "type": "sellmeier",
        "B": [1.03961212, 0.231792344, 1.01046945],
        "C": [0.00600069867, 0.0200179144, 103.560653],
        "n_d": 1.5168,
        "Vd": 64.17,
    },
    "Fused Silica": {
        "type": "sellmeier",
        "B": [0.6961663, 0.4079426, 0.8974794],
        "C": [0.00467914826, 0.0135120631, 97.9340025],
        "n_d": 1.4585,
        "Vd": 67.8,
    },
    "N-SF11": {
        "type": "sellmeier",
        "B": [1.73759695, 0.313747346, 1.89878101],
        "C": [0.013188707, 0.0623068142, 155.23629],
        "n_d": 1.7847,
        "Vd": 25.76,
    },
    "N-BK10": {
        "type": "sellmeier",
        "B": [1.2492666, 0.34465909, 1.6596812],
        "C": [0.008573, 0.032937, 109.959],  # µm²
        "n_d": 1.4978,
        "Vd": 66.9,
    },
    "N-K5": {
        "type": "sellmeier",
        "B": [1.085137, 0.199562, 1.0121],
        "C": [0.006610995, 0.020017914, 103.560653],
        "n_d": 1.5225,
        "Vd": 59.5,
    },
    "N-K7": {
        "type": "sellmeier",
        "B": [1.1273555, 0.12441230, 0.82710053],
        "C": [0.00720341707, 0.0269835916, 100.384588],
        "n_d": 1.5111,
        "Vd": 60.4,
    },
    # --------------------------------------------------
    # Optical glass (Abbe fallback)
    # --------------------------------------------------
    "F2": {
        "type": "abbe",
        "n_d": 1.6200,
        "Vd": 36.37,
    },
    "SF2": {
        "type": "abbe",
        "n_d": 1.6477,
        "Vd": 33.85,
    },
    # --------------------------------------------------
    # Kristaller
    # --------------------------------------------------
    "Sapphire": {
        "type": "abbe",
        "n_d": 1.7680,
        "Vd": 72.2,
    },
    "Zinc Selenide": {
        "type": "constant",  # IR-material – ofta konstant används
        "n": 2.4030,
    },
    # --------------------------------------------------
    # Plast
    # --------------------------------------------------
    "Acrylic (PMMA)": {
        "type": "abbe",
        "n_d": 1.4910,
        "Vd": 57.2,
    },
    "Polycarbonate": {
        "type": "abbe",
        "n_d": 1.5850,
        "Vd": 29.9,
    },
    # --------------------------------------------------
    # Vätskor / Luft
    # --------------------------------------------------
    "Water": {
        "type": "abbe",
        "n_d": 1.3330,
        "Vd": 55.7,
    },
    "Air": {
        "type": "constant",
        "n": 1.0003,
    },
}


# --------------------------------------------------
# Hjälpfunktioner
# --------------------------------------------------


def get_material_list():
    """Returnerar sorterad lista med materialnamn, med 'Air' först."""
    return ["Air"] + sorted(m for m in MATERIAL_DATA if m != "Air")


def get_material_params(name):
    data = MATERIAL_DATA.get(name, {})

    n = data.get("n_d", data.get("n", 1.5168))
    v = data.get("Vd", 55.0)

    return n, v


def sellmeier_n(wavelength_nm, B, C):
    lam = wavelength_nm / 1000.0
    lam2 = lam * lam

    n2 = 1.0
    for b, c in zip(B, C):
        denom = lam2 - c
        if abs(denom) < 1e-9:
            continue
        n2 += b * lam2 / denom

    return n2**0.5


def get_refractive_index(name, wavelength_nm=550.0, override_n=None):

    if override_n is not None:
        return override_n

    data = MATERIAL_DATA.get(name)

    if not data:
        return 1.5

    mat_type = data.get("type", "abbe")

    # -----------------------------
    # CONSTANT
    # -----------------------------
    if mat_type == "constant":
        return data["n"]

    # -----------------------------
    # SELLMEIER
    # -----------------------------
    # if mat_type == "sellmeier":
    #     return sellmeier_n(wavelength_nm, data["B"], data["C"])

    if mat_type == "sellmeier":
        B = data.get("B")
        C = data.get("C")

        if B and C:
            return sellmeier_n(wavelength_nm, B, C)
        else:
            mat_type = "abbe"

    # -----------------------------
    # ABBE (fallback)
    # -----------------------------
    n_d = data.get("n_d", 1.5)
    v_d = data.get("Vd", 50.0)

    if v_d <= 0:
        return n_d

    offset = (wavelength_nm - 587.6) / 1000.0
    return n_d - (offset * (n_d - 1.0) / v_d)


def get_refractive_index_old(name, wavelength_nm=550.0, override_n=None):
    """
    Returnerar brytningsindex vid given våglängd.

    - name: materialnamn
    - wavelength_nm: våglängd i nm
    - override_n: direkt n-värde (t.ex. för Custom/lins)

    Använder enkel Abbe-baserad linjär approximation.
    """

    # Om objektet själv anger n (t.ex. Custom-lins)
    if override_n is not None:
        return override_n

    n_d, v_d = MATERIAL_DATA.get(name, (1.5168, 55.0))

    if n_d is None:
        return 1.5  # extrem fallback

    # Ingen dispersion definierad
    if not v_d or v_d <= 0:
        return n_d

    # Enkel Abbe-approximation kring d-linjen
    # Blått bryts mer (kort λ), rött mindre
    offset = (wavelength_nm - 587.6) / 1000.0
    return n_d - (offset * (n_d - 1.0) / v_d)
