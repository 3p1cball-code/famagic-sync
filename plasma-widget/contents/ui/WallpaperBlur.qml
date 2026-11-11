import QtQuick
import QtQuick.Effects
import org.kde.plasma.plasmoid

/*
 * The card every one of these desktop widgets sits on: a blurred copy of the
 * wallpaper directly behind it, a dark tint, and a hairline frame.
 *
 * Desktop widgets live in the same window as the wallpaper, so KWin's
 * blur-behind cannot reach them. Instead the containment's live wallpaper
 * item is grabbed with a ShaderEffectSource (the part under the widget plus
 * a margin, so the blur has real pixels to pull in at the edges) and blurred
 * with MultiEffect. Because it renders the real wallpaper item, it follows
 * slideshows, colour wallpapers and any fill mode automatically.
 *
 * Shape: a rounded rectangle (radius), or any item given as maskItem - its
 * alpha decides where the card is (deebot-map uses the room floor plan).
 *
 * Shared between regenradar, famagic and deebot-map - keep the copies equal.
 */
Item {
    id: bw

    property real blur: 0.5               // 0..1, 0 = off
    property color tint: "transparent"    // drawn over the blur, inside the shape
    property real radius: 0               // corner radius of the card
    property bool frame: false            // hairline outline (rounded shape only)
    property Item maskItem: null          // optional: alpha mask, same geometry as bw
    property int blurMax: 64              // px at blur = 1.0

    readonly property int pad: blurMax
    property var wallpaper: null
    readonly property bool blurActive: blur > 0.001 && wallpaper !== null && width > 0 && height > 0
    readonly property bool shown: blurActive || tint.a > 0.004

    // grab = region in wallpaper coordinates, offset = its origin relative to bw
    property rect grab: Qt.rect(0, 0, 0, 0)
    property point offset: Qt.point(0, 0)

    function findWallpaper() {
        var w = null;
        var c = Plasmoid.containment;
        if (c && c.wallpaperGraphicsObject)
            w = c.wallpaperGraphicsObject;
        for (var p = bw.parent; !w && p; p = p.parent) {
            if (p.wallpaper)
                w = p.wallpaper;
        }
        if (w !== bw.wallpaper) {
            bw.wallpaper = w;
            if (w) {
                w.widthChanged.connect(bw.updateRegion);
                w.heightChanged.connect(bw.updateRegion);
            }
        }
        bw.updateRegion();
    }

    function updateRegion() {
        var w = bw.wallpaper;
        if (!w || bw.width <= 0 || bw.height <= 0)
            return;
        var p = w.mapFromItem(bw, 0, 0);
        var x0 = Math.max(0, Math.floor(p.x - bw.pad));
        var y0 = Math.max(0, Math.floor(p.y - bw.pad));
        var x1 = Math.min(w.width, Math.ceil(p.x + bw.width + bw.pad));
        var y1 = Math.min(w.height, Math.ceil(p.y + bw.height + bw.pad));
        var r = Qt.rect(x0, y0, Math.max(1, x1 - x0), Math.max(1, y1 - y0));
        if (r.x !== grab.x || r.y !== grab.y || r.width !== grab.width || r.height !== grab.height)
            grab = r;
        var o = Qt.point(x0 - p.x, y0 - p.y);
        if (o.x !== offset.x || o.y !== offset.y)
            offset = o;
    }

    // Follow moves of the widget: every ancestor's x/y feeds the mapping.
    function hookAncestors() {
        for (var p = bw; p; p = p.parent) {
            p.xChanged.connect(bw.updateRegion);
            p.yChanged.connect(bw.updateRegion);
        }
    }

    onWidthChanged: updateRegion()
    onHeightChanged: updateRegion()
    onParentChanged: if (parent) { hookAncestors(); findWallpaper(); }
    Component.onCompleted: { hookAncestors(); findWallpaper(); }

    // Fallback: the wallpaper item can appear after the applet, and some
    // geometry changes (screen layout) do not move any ancestor.
    Timer {
        interval: bw.wallpaper ? 3000 : 1000
        running: bw.blur > 0.001 && bw.visible
        repeat: true
        onTriggered: bw.wallpaper ? bw.updateRegion() : bw.findWallpaper()
    }

    Item {
        id: clipper
        anchors.fill: parent
        clip: true
        visible: bw.shown
        layer.enabled: visible && (bw.maskItem !== null || bw.radius > 0)
        layer.effect: MultiEffect {
            maskEnabled: true
            maskSource: bw.maskItem !== null ? bw.maskItem : roundMask
            maskThresholdMin: 0.5
            maskSpreadAtMin: 1.0
        }

        ShaderEffectSource {
            id: src
            x: bw.offset.x
            y: bw.offset.y
            width: bw.grab.width
            height: bw.grab.height
            sourceItem: bw.blurActive ? bw.wallpaper : null
            sourceRect: bw.grab
            live: true
            hideSource: false
            recursive: false
            visible: false
        }

        MultiEffect {
            x: src.x
            y: src.y
            width: src.width
            height: src.height
            visible: bw.blurActive
            source: src
            autoPaddingEnabled: false
            blurEnabled: true
            blur: bw.blur
            blurMax: bw.blurMax
        }

        Rectangle {
            anchors.fill: parent
            color: bw.tint
            visible: bw.tint.a > 0.004
        }
    }

    Item {
        id: roundMask
        anchors.fill: parent
        visible: false
        layer.enabled: true
        Rectangle {
            anchors.fill: parent
            radius: bw.radius
            color: "black"
        }
    }

    Rectangle {
        anchors.fill: parent
        visible: bw.frame && bw.maskItem === null
        radius: bw.radius
        color: "transparent"
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.12)
    }
}
