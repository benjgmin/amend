import SwiftUI

/// "Coming up at your airports" (before the 0901Z changeover) or "This cycle at your airports" (after): one row per
/// airport you keep that changes, busiest first, with its counts. Tap a row for its top changes; the arrow opens it.
/// The site shows every change inline; on a phone that pushed your lists several screens down.
struct ComingUpView: View {
    @Environment(AirportStore.self) private var store
    let meta: Meta
    var open: (String) -> Void = { _ in }
    @State private var expanded: Set<String> = []

    private var upcoming: Bool { meta.upcoming && !Cycle.isInEffect(meta.toCycle) }

    var body: some View {
        let kept = store.saved
        let busy = store.busyKept
        let shown = busy.prefix(60)
        let quiet = kept.filter { store.counts(for: $0) == nil }.sorted()

        // separate list rows (the list flattens this Group), so each airport is its own tap target
        Group {
            // no countdown here: the cycle panel at the top already has it
            EFBHeader(text: upcoming ? "Coming up at your airports" : "This cycle at your airports")
                .efbRow(top: 20, bottom: 2)
            .task(id: busy) { await store.loadKept() }

            if busy.isEmpty {
                note("Nothing \(upcoming ? "changes" : "changed") at your \(kept.count) airport\(kept.count == 1 ? "" : "s") this cycle.")
            }
            ForEach(shown, id: \.self) { id in
                let data = store.latest[id]
                ComingUpRow(id: id, info: store.info(for: id), counts: store.counts(for: id), data: data,
                            tags: store.lists.count > 1 ? store.listsContaining(id).map(\.name) : [],
                            fresh: data.map { store.newIDs(id, $0.changes, cycle: $0.toCycle) } ?? [],
                            isOpen: expanded.contains(id),
                            toggle: {
                                withAnimation(.snappy(duration: 0.2)) {
                                    if expanded.contains(id) { expanded.remove(id) } else { expanded.insert(id) }
                                }
                            },
                            open: { open(id) })
                    .efbRow(top: 2, bottom: 2)
            }
            if busy.count > 60 {
                note("Showing the 60 busiest of \(busy.count) airports with changes. Each list has all of them.")
            }
            if !busy.isEmpty && !quiet.isEmpty {
                note("No change at \(quiet.joined(separator: ", "))")
            }
        }
    }

    private func note(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 13))
            .foregroundStyle(EFB.dim)
            .fixedSize(horizontal: false, vertical: true)
            .efbRow(top: 3, bottom: 3)
    }
}

private struct ComingUpRow: View {
    let id: String
    let info: AirportInfo?
    let counts: Counts?
    /// nil until its changes load; the row shows from the counts alone until then
    let data: AirportChanges?
    let tags: [String]
    /// changes not there the last time you looked
    let fresh: Set<String>
    let isOpen: Bool
    let toggle: () -> Void
    let open: () -> Void

    /// top few only; the airport page has the rest
    private static let top = 3

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Button(action: toggle) {
                    HStack(spacing: 8) {
                        Image(systemName: "chevron.right")
                            .font(.system(size: 11, weight: .bold))
                            .foregroundStyle(EFB.faint)
                            .rotationEffect(.degrees(isOpen ? 90 : 0))
                        Text(id).font(EFB.mono(16, .semibold)).foregroundStyle(EFB.text).fixedSize()
                        Text(info?.name ?? "")
                            .font(.system(size: 13))
                            .foregroundStyle(EFB.dim)
                            .lineLimit(1)
                        Spacer(minLength: 4)
                        if !fresh.isEmpty { NewPill(count: fresh.count) }
                        CountAnnunciators(counts: counts ?? data?.counts)
                    }
                    .padding(.vertical, 11)
                    .padding(.leading, 12)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("\(id), \(info?.name ?? "")")
                .accessibilityHint(isOpen ? "Hides its changes" : "Shows its top changes")

                Button(action: open) {
                    Image(systemName: "arrow.up.right.square")
                        .font(.system(size: 17))
                        .foregroundStyle(EFB.cyan)
                        .frame(width: 40, height: 40)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.borderless)
                .padding(.trailing, 4)
                .accessibilityLabel("Open \(id)")
            }

            if isOpen {
                VStack(alignment: .leading, spacing: 7) {
                    if let data {
                        ForEach(data.changes.prefix(Self.top)) { c in
                            HStack(alignment: .firstTextBaseline, spacing: 8) {
                                Text(c.level.short)
                                    .font(.system(size: 10.5, weight: .bold))
                                    .tracking(0.5)
                                    .foregroundStyle(c.level.color)
                                    .frame(width: 26, alignment: .leading)
                                Text((fresh.contains(c.id) ? "New · " : "") + sentence(c.summary))
                                    .font(.system(size: 14))
                                    .foregroundStyle(EFB.text.opacity(0.9))
                                    .lineLimit(3)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        // which of your lists it's on; with one list it would say the same everywhere
                        if !tags.isEmpty {
                            Text("On " + tags.joined(separator: ", "))
                                .font(.system(size: 12))
                                .foregroundStyle(EFB.faint)
                        }
                        Button(action: open) {
                            Text(data.changes.count > Self.top
                                 ? "All \(data.changes.count) changes at \(id) ›"
                                 : "Open \(id) ›")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(EFB.cyan)
                        }
                        .buttonStyle(.borderless)
                    } else {
                        ProgressView().controlSize(.small)
                    }
                }
                .padding(.horizontal, 14)
                .padding(.bottom, 12)
                .transition(.opacity)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(EFB.panel, in: RoundedRectangle(cornerRadius: EFB.radius))
        .overlay(RoundedRectangle(cornerRadius: EFB.radius).stroke(EFB.line, lineWidth: 1))
    }

    private func sentence(_ s: String) -> String {
        let t = s.replacingOccurrences(of: " -> ", with: " → ")
        return t.prefix(1).uppercased() + t.dropFirst()
    }
}

/// "in 2d 9h 14m", ticking, by the server-checked clock (the site's format)
struct Countdown: View {
    let to: Date

    var body: some View {
        TimelineView(.periodic(from: .now, by: 15)) { _ in
            Text(text(to.timeIntervalSince(ServerClock.now)))
                .monospacedDigit()
        }
    }

    private func text(_ seconds: TimeInterval) -> String {
        guard seconds > 0 else { return "now" }
        guard seconds >= 60 else { return "in under 1m" }
        let m = Int(seconds / 60), d = m / 1440, h = m % 1440 / 60, mm = m % 60
        return "in " + (d > 0 ? "\(d)d " : "") + (d > 0 || h > 0 ? "\(h)h " : "") + "\(mm)m"
    }
}
