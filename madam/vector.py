def svg_length_to_px(length):
    if length is None:
        raise ValueError()

    INCH_TO_MM = 1/25.4
    PX_PER_INCH = 90
    PT_PER_INCH = 1/72
    FONT_SIZE_PT = 12
    X_HEIGHT = 0.7

    unit_len = 2
    if length.endswith('%'):
        unit_len = 1
    try:
        value = float(length)
        unit = 'px'
    except ValueError:
        value = float(length[:-unit_len])
        unit = length[-unit_len:]

    if unit == 'em':
        return value * PX_PER_INCH * FONT_SIZE_PT * PT_PER_INCH
    elif unit == 'ex':
        return value * PX_PER_INCH * X_HEIGHT * FONT_SIZE_PT * PT_PER_INCH
    elif unit == 'px':
        return value
    elif unit == 'in':
        return value * PX_PER_INCH
    elif unit == 'cm':
        return value * PX_PER_INCH * INCH_TO_MM * 10
    elif unit == 'mm':
        return value * PX_PER_INCH * INCH_TO_MM
    elif unit == 'pt':
        return value * PX_PER_INCH * PT_PER_INCH
    elif unit == 'pc':
        return value * PX_PER_INCH * PT_PER_INCH * 12
    elif unit == '%':
        return value
