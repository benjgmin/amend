import SwiftUI

struct ChangeRow: View {
    let change: Change
    /// the cycle this change belongs to, for its FAA source link (history entries carry their own)
    var cycle: String? = nil
    /// not there the last time you looked at this airport
    var isNew = false
    @State private var expanded = false
    @State private var plate: Plate?

    private var hasMore: Bool {
        change.original != nil || !(change.details ?? []).isEmpty
    }

    /// "View plate" already opens the official chart, so a chart with a plate needs no other source link
    private var sourceURL: URL? {
        change.chart?.pdf != nil ? nil : FAALinks.source(for: change, cycle: cycle)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                RoundedRectangle(cornerRadius: 1)   // priority bar
                    .fill(change.level.color)
                    .frame(width: 3, height: 11)
                    .accessibilityHidden(true)
                Text(displayCategory)
                    .font(.system(size: 11.5))
                    .tracking(0.55)
                    .textCase(.uppercase)
                    .foregroundStyle(EFB.faint)
            }
            if isNew { NewPill() }
            Text(displaySummary)
                .font(.system(size: 15))
                .foregroundStyle(EFB.text)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)

            // a remark that still reads in FAA words says why, like the site
            if let why = change.untranslated, !why.isEmpty {
                Text(why)
                    .font(.system(size: 13))
                    .foregroundStyle(EFB.dim)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if hasMore || change.chart?.amdtLabel != nil || change.chart?.pdf != nil || sourceURL != nil {
                HStack(spacing: 12) {
                    if let amdt = change.chart?.amdtLabel {
                        Annunciator(text: amdt, color: EFB.dim)
                    }
                    if let pdf = change.chart?.pdf, let url = URL(string: pdf) {
                        Button {
                            plate = Plate(url: url, title: change.chart?.name ?? "Chart")
                        } label: {
                            Label("View plate", systemImage: "doc.richtext")
                                .font(.system(size: 13.5, weight: .medium))
                                .foregroundStyle(EFB.cyan)
                        }
                        .buttonStyle(.plain)
                    }
                    if hasMore {
                        Button { withAnimation(.snappy) { expanded.toggle() } } label: {
                            HStack(spacing: 3) {
                                Text(expanded ? "Hide" : (change.original != nil ? "FAA text" : "Details"))
                                Image(systemName: expanded ? "chevron.up" : "chevron.down")
                                    .font(.system(size: 10, weight: .semibold))
                            }
                            .font(.system(size: 13.5, weight: .medium))
                            .foregroundStyle(EFB.cyan)
                        }
                        .buttonStyle(.plain)
                    }
                    Spacer(minLength: 0)
                    if let url = sourceURL {
                        Link(destination: url) {
                            Text("FAA source ↗")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(EFB.dim)
                        }
                        .buttonStyle(.borderless)   // in a list row, only the link itself is the tap target
                        .accessibilityLabel("FAA source, opens the FAA website")
                    }
                }
                .padding(.top, 2)
            }

            if expanded {
                VStack(alignment: .leading, spacing: 6) {
                    if let original = change.original {
                        Text(original)
                            .font(EFB.mono(12))
                            .foregroundStyle(EFB.dim)
                            .textSelection(.enabled)
                    }
                    ForEach(change.details ?? [], id: \.self) { line in
                        Text(line.replacingOccurrences(of: " -> ", with: " → "))
                            .font(EFB.mono(12))
                            .foregroundStyle(EFB.dim)
                            .textSelection(.enabled)
                    }
                }
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(EFB.panelHi, in: RoundedRectangle(cornerRadius: 8))
                .padding(.top, 4)
            }
        }
        .padding(.vertical, 12)
        .padding(.horizontal, 14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(EFB.panel)
        .clipShape(RoundedRectangle(cornerRadius: EFB.radius))
        .overlay(RoundedRectangle(cornerRadius: EFB.radius).stroke(EFB.line, lineWidth: 1))
        .fullScreenCover(item: $plate) { PlateView(plate: $0) }
    }

    /// "frequency" -> "Frequency"
    private var displayCategory: String {
        change.category.prefix(1).uppercased() + change.category.dropFirst()
    }

    /// capitalize the first letter; the backend writes lowercase summaries
    private var displaySummary: String {
        let s = change.summary.replacingOccurrences(of: " -> ", with: " → ")
        return s.prefix(1).uppercased() + s.dropFirst()
    }
}
