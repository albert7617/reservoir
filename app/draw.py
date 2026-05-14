import cairo
import io
from datetime import datetime

WORST_YEAR = 2021

def tsv_to_dict(tsv: str):
    lines = tsv.split("\n")
    reservoir_history = {}
    reservoir_capacity = {}
    reservoir_current = {}

    for i, line in enumerate(lines):
        if not line:
            break

        reservoir, capacity, current, ymd = line.split("\t")
        year_str = ymd.split('-')[0]
        year = int(year_str)

        # Init nested dicts
        if reservoir not in reservoir_history:
            reservoir_history[reservoir] = {}
        if year not in reservoir_history[reservoir]:
            reservoir_history[reservoir][year] = {}

        # Store current record
        reservoir_history[reservoir][year][ymd] = float(current)

        # Update capacity and current status
        cap_val = float(capacity)
        reservoir_capacity[reservoir] = cap_val if cap_val > 1 else reservoir_capacity.get(reservoir)

        if float(current) > 0 and (len(lines) - i) < 5:
            reservoir_current[reservoir] = float(current)

    return reservoir_capacity, reservoir_history, reservoir_current

def plot_reservoir(reservoir, width, height, full_tsv, curr_tsv) -> str:
    # Headroom to prevent 100% capacity lines from hitting the SVG border
    Y_AXIS_CEILING_PCT = 103
    reservoir_capacity, reservoir_history, reservoir_current = tsv_to_dict(full_tsv)
    data = reservoir_history.get(reservoir, {})
    max_val = reservoir_capacity.get(reservoir, 1)
    # Setup dimensions
    chart_top, chart_bottom = 0, height - 16
    this_year = datetime.now().year
    target_years = [WORST_YEAR, this_year - 1, this_year]

    # Init SVG surface
    f = io.BytesIO()
    surface = cairo.SVGSurface(f, width, height)
    ctx = cairo.Context(surface)

    # Text & Months
    ctx.select_font_face("Noto Sans TC",
                         cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(20)

    # Center reservoir name at top
    xbear, ybear, t_width, t_height, xadv, yadv = ctx.text_extents(reservoir)
    ctx.move_to((width / 2) - (t_width / 2) - xbear, chart_top + t_height + 2)
    ctx.set_source_rgba(0, 0, 0, 0.6) # Subtle grey-black
    ctx.show_text(reservoir)

    chart_top = t_height + 10  # Increased from 6 to make room for title

    # Month labels (rest of existing code)
    ctx.set_font_size(12)
    ctx.select_font_face("Noto Sans TC",
                         cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)

    # Helper for Y scaling
    def get_y(val):
        # 1. Clamp values exceeding capacity to exactly 100% (max_val)
        clamped_val = min(val, max_val)
        # 2. Set the top of the plot area to 103% of capacity
        plot_max = max_val * (Y_AXIS_CEILING_PCT / 100)
        # 3. Calculate percentage relative to the 103% ceiling
        pct = clamped_val / plot_max
        # 4. Map to SVG coordinates
        return chart_top + (1.0 - pct) * (chart_bottom - chart_top)

    last_x, last_y = 0, 0

    # Draw lines
    for year_str, dates in data.items():
        year = int(year_str)
        if year not in target_years:
            continue
        last_amount = 0
        year_start = datetime(year, 1, 1)
        total_day_of_year = (datetime(year + 1, 1, 1) - datetime(year, 1, 1)).days


        print(f"Plotting {reservoir} for year {year} with {len(dates)} data points, max capacity {max_val}")  # Debug statement

        ctx.set_line_width(2.5)
        if year == this_year:
            ctx.set_source_rgba(0, 0, 0, 1.0)
        elif year == this_year - 1:
            ctx.set_source_rgba(0, 0, 0, 0.5)
        else:
            ctx.set_source_rgba(0, 0, 0, 0.25)

        first = True
        for ymd, amount in dates.items():
            amount = amount if amount > 0 else last_amount

            dt = datetime.strptime(ymd, "%Y-%m-%d")
            day_of_year = (dt - year_start).days

            x = width * day_of_year / total_day_of_year
            y = get_y(amount)

            if first:
                ctx.move_to(x, y)
                first = False
            else:
                ctx.line_to(x, y)

            last_amount = amount
            last_x, last_y = x, y

        ctx.stroke()

    # Grid lines
    ctx.set_source_rgb(0.3, 0.3, 0.3)
    ctx.set_line_width(1)
    grid_pts = [
        (1, chart_top + 1), (1, chart_bottom - 1),
        (width - 1, chart_bottom - 1), (width - 1, chart_top + 1)
    ]
    ctx.move_to(5, chart_top + 1)
    for px, py in grid_pts:
        ctx.line_to(px, py)
    ctx.line_to(width - 5, chart_top + 1)
    ctx.stroke()

    # Text & Months
    ctx.select_font_face("Noto Sans TC",
                         cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(12)

    months = [
        (20, '二月'), (80, '四月'), (141, '六月'),
        (202, '八月'), (263, '十月'), (320, '十二月')
    ]
    for day, name in months:
        mx = width * day / 365
        ctx.move_to(mx, height - 4)
        ctx.show_text(name)

    # Vertical grid lines
    months = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    ctx.set_dash([2.0, 4.0], 0)
    for day in months:
        mx = width * day / 365
        ctx.move_to(mx, chart_top)
        ctx.line_to(mx, chart_bottom)
        ctx.stroke()
    # reset to solid

    # Horizontal grid lines
    quater = [25, 50, 75, 100]
    for q in quater:
        my = chart_top + (1.0 - q / Y_AXIS_CEILING_PCT) * (chart_bottom - chart_top)
        ctx.move_to(0, my)
        ctx.line_to(width, my)
        ctx.stroke()
    # reset to solid
    ctx.set_dash([])

    # Endpoint dot
    ctx.set_source_rgb(0, 0, 0)
    ctx.arc(last_x, last_y, 3, 0, 2 * 3.14159)
    ctx.fill()

    surface.finish()
    return f.getvalue().decode("utf-8")

def plot_legend(width, height) -> str:
    this_year = datetime.now().year

    class LegendEntry:
        def __init__(self, year, desc, alpha):
            self.year = year
            self.desc = desc
            self.alpha = alpha

    entries = [LegendEntry(this_year, "今年", 1.0),
               LegendEntry(this_year - 1, "去年", 0.5),
               LegendEntry(WORST_YEAR, "百年大旱(2021)", 0.25),]
    line_length = 10
    line_text_spacing = 6

    # Init SVG surface
    f = io.BytesIO()
    surface = cairo.SVGSurface(f, width, height)
    ctx = cairo.Context(surface)

    ctx.set_source_rgba(0, 0, 0, 0.6) # Subtle grey-black
    ctx.set_font_size(12)
    ctx.select_font_face("Noto Sans TC",
                         cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)

    total_text_width = 0
    total_line_width = 0
    for entry in entries:
        xbear, ybear, t_width, t_height, xadv, yadv = ctx.text_extents(entry.desc)
        total_text_width += t_width
        total_line_width += (line_length + line_text_spacing)
    total_spacing = width - total_text_width - total_line_width
    spacing_between = total_spacing / (len(entries) + 1)

    x_cursor = spacing_between

    for entry in entries:
        # Draw line
        ctx.set_source_rgba(0, 0, 0, entry.alpha)
        ctx.set_line_width(5)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.move_to(x_cursor, height/2)
        ctx.line_to(x_cursor + line_length, height/2)
        ctx.stroke()
        x_cursor += (line_length + line_text_spacing)

        # Draw text
        ctx.set_source_rgba(0, 0, 0, 1.0)
        xbear, ybear, t_width, t_height, xadv, yadv = ctx.text_extents(entry.desc)
        ctx.move_to(x_cursor, height/2 + t_height/2 - 3)
        ctx.show_text(entry.desc)
        x_cursor += (t_width + spacing_between)


    surface.finish()
    return f.getvalue().decode("utf-8")

