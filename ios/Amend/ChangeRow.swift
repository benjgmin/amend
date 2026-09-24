import SwiftUI

struct ChangeRow: View {
    let change: Change
    @State private var expanded = false
    @State private var plate: Plate?

    private var hasMore: Bool {
        change.original != nil || !(change.details ?? []).isEmpty
    }

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            Rectangle()                       // priority bar
                .fill(change.level.color)
                .frame(width: 3)
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: icon)
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(change.level.color)
                        .frame(width: 20)
                        .accessibilityHidden(true)
                    Text(displaySummary)
                        .font(.system(size: 15))
                        .foregroundStyle(EFB.text)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                }

                HStack(spacing: 6) {
                    Text(change.category.uppercased())
                        .font(EFB.mono(9, .semibold))
                        .tracking(1)
                        .foregroundStyle(EFB.faint)
                    if let amdt = change.chart?.amdtLabel {
                        Annunciator(text: amdt, color: EFB.dim)
                    }
                    Spacer()
                    if let pdf = change.chart?.pdf, let url = URL(string: pdf) {
                        Button {
                            plate = Plate(url: url, title: change.chart?.name ?? "Chart")
                        } label: {
                            Text("VIEW PLATE ›")
                                .font(EFB.mono(11, .bold))
                                .foregroundStyle(EFB.cyan)
                        }
                        .buttonStyle(.plain)
                    }
                    if hasMore {
                        Button { withAnimation(.snappy) { expanded.toggle() } } label: {
                            Text(expanded ? "HIDE ▾" : (change.original != nil ? "FAA TEXT ▸" : "DETAILS ▸"))
                                .font(EFB.mono(11, .bold))
                                .foregroundStyle(EFB.dim)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.leading, 30)

                if expanded {
                    VStack(alignment: .leading, spacing: 6) {
                        if let original = change.original {
                            Text(original)
                                .font(EFB.mono(11))
                                .foregroundStyle(EFB.amber.opacity(0.85))
                                .textSelection(.enabled)
                        }
                        ForEach(change.details ?? [], id: \.self) { line in
                            Text(line)
                                .font(EFB.mono(11))
                                .foregroundStyle(EFB.dim)
                                .textSelection(.enabled)
                        }
                    }
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(EFB.bg, in: RoundedRectangle(cornerRadius: 5))
                    .padding(.leading, 30)
                }
            }
            .padding(.vertical, 10)
            .padding(.horizontal, 10)
        }
        .background(EFB.panel)
        .clipShape(RoundedRectangle(cornerRadius: 6))
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(EFB.line, lineWidth: 1))
        .fullScreenCover(item: $plate) { PlateView(plate: $0) }
    }

    /// capitalize the first letter; the backend writes lowercase summaries
    private var displaySummary: String {
        change.summary.prefix(1).uppercased() + change.summary.dropFirst()
    }

    private var icon: String {
        switch change.category {
        case "tower": "antenna.radiowaves.left.and.right"
        case "airspace": "circle.dashed"
        case "frequency": "dot.radiowaves.left.and.right"
        case "navaid": "location.north.circle"
        case "runway": "road.lanes"
        case "remark": "text.bubble"
        case "procedure": "arrow.triangle.turn.up.right.diamond"
        case "route": "point.topleft.down.to.point.bottomright.curvepath"
        case "chart": "doc.richtext"
        case "weather": "cloud.sun"
        case "airport": "airplane"
        default: "info.circle"
        }
    }
}
