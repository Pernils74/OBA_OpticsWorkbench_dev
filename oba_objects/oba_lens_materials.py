# oba_lens_materials.py

# Struktur: "Namn": (Brytningsindex n_d, Abbe-tal V_d)
# n_d avser d-linjen (587.6 nm)
# Abbe-tal: Högt = låg dispersion, Lågt = hög dispersion

MATERIAL_DATA = {
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


# --------------------------------------------------
# Hjälpfunktioner
# --------------------------------------------------


def get_material_list():
    """Returnerar sorterad lista med materialnamn."""
    return sorted(MATERIAL_DATA.keys())


def get_material_params(name):
    """
    Returnerar (n_d, V_d).
    Faller tillbaka på BK7-liknande värden.
    """
    return MATERIAL_DATA.get(name, (1.5168, 55.0))


def get_refractive_index(name, wavelength_nm=550.0, override_n=None):
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
