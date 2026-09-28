import SwiftUI

/// "Coming up at your airports" (before the 0901Z changeover) or "This cycle at your airports" (after): the top
/// changes at every airport you keep, with a live countdown, like the block on the site's home page
struct ComingUpView: View {
    @Environment(AirportStore.self) private var store
    let meta: Meta

    private var upcoming: Bool { meta.upcoming && !Cycle.isInEffect(meta.toCycle) }

    /// the changeover it counts down to: this cycle's, or the next one once this is in effect
    private var target: Date? {
        Cycle.effectiveInstant(upcoming ? meta.toCycle : Cycle.shift(meta.toCycle, days: 28))
    }

    var body: some View {
        let kept = store.saved
        let busy = store.busyKept
        let shown = busy.prefix(60).filter { store.latest[$0] != nil }
        let quiet = kept.filter { store.counts(for: $0) == nil }.sorted()

        // separate list rows (the list flattens this Group), so each airport is its own tap target
        Group {
            HStack(alignment: .firstTextBaseline) {
                EFBHeader(text: upcoming ? "Coming up at your airports" : "This cycle at your airports")
                Spacer(minLength: 8)
                if let target {
                    HStack(spacing: 4) {
                        Text(upcoming ? "Takes effect" : "Next cycle")
                        Countdown(to: target)
                    }
                    .font(.system(size: 12.5))
                    .foregroundStyle(EFB.faint)
                }
            }
            .efbRow(top: 4, bottom: 2)
            .task(id: busy) { await store.loadKept() }

            if busy.isEmpty {
                note("Nothing \(upcoming ? "changes" : "changed") at your \(kept.count) airport\(kept.count == 1 ? "" : "s") this cycle.")
            }
            ForEach(shown, id: \.self) { id in
                if let data = store.latest[id] {
                    ZStack {
                        NavigationLink(value: id) { EmptyView() }.opacity(0)
                        ComingUpRow(id: id, info: store.info(for: id), data: data,
                                    tags: store.lists.count > 1 ? store.listsContaining(id).map(\.name) : [])
                    }
                    .efbRow(top: 3, bottom: 3)
                }
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
    let data: AirportChanges
    let tags: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(id).font(EFB.mono(16, .semibold)).foregroundStyle(EFB.text)
                Text(info?.name ?? "")
                    .font(.system(size: 13))
                    .foregroundStyle(EFB.dim)
                    .lineLimit(1)
                Spacer(minLength: 4)
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(EFB.faint)
            }
            HStack(spacing: 6) {
                CountAnnunciators(counts: data.counts)
                // which of your lists it's on; with one list it would say the same everywhere
                ForEach(tags, id: \.self) { tag in
                    Text(tag)
                        .font(.system(size: 11.5, weight: .medium))
                        .lineLimit(1)
                        .foregroundStyle(EFB.dim)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(EFB.panelHi, in: RoundedRectangle(cornerRadius: 3))
                }
            }
            ForEach(data.changes.prefix(3)) { c in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(c.level.short)
                        .font(.system(size: 10.5, weight: .bold))
                        .tracking(0.5)
                        .foregroundStyle(c.level.color)
                        .frame(width: 26, alignment: .leading)
                    Text(sentence(c.summary))
                        .font(.system(size: 14))
                        .foregroundStyle(EFB.text.opacity(0.9))
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            if data.changes.count > 3 {
                Text("\(data.changes.count - 3) more ›")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(EFB.cyan)
            }
        }
        .efbPanel()
        .contentShape(Rectangle())
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
