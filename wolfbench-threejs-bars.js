import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.160.1/build/three.module.js';

(function() {
    var chartArea = document.querySelector('.chart-area');
    if (!chartArea) return;

    var tokenDepthModes = ['flat', 'tokens', 'cost', 'both'];
    var renderer = null;
    var scene = null;
    var camera = null;
    var canvas = null;
    var labelLayer = null;
    var root = null;
    var queued = false;
    var settleQueued = false;
    var materials = new Map();
    var baseSegmentOrder = ['solid', 'worst', 'average', 'best', 'ceiling'];
    var metricLabels = {
        solid: 'Solid base',
        worst: 'Worst-of',
        average: 'Average',
        best: 'Best-of',
        ceiling: 'Ceiling'
    };
    var tokensPerDepthPixel = 1e7;
    var costPerDepthPixel = 5;
    var projectX = 0.74;
    var projectY = 0.31;
    var projectZ = 0.28;
    var segmentGap = 0;
    var tokenGap = 0;
    var missingDepth = 2;
    var spacedVisualGap = 8;
    var depthLabelAngle = -Math.atan2(projectY, projectX) * 180 / Math.PI;
    var shearMatrix = new THREE.Matrix4().set(
        1, 0, projectX, 0,
        0, 1, projectY, 0,
        0, 0, -projectZ, 0,
        0, 0, 0, 1
    );

    chartArea.classList.add('three-bars');

    function normalizeTokenDepthMode(mode) {
        if (mode === 'overlap' || mode === 'spaced' || mode === 'on' || mode === '3d') return 'tokens';
        if (mode === 'tokens' || mode === 'token') return 'tokens';
        if (mode === 'cost' || mode === 'costs' || mode === 'usd') return 'cost';
        if (mode === 'both' || mode === 'tokens+cost' || mode === 'tokens-cost' || mode === 'token+cost' || mode === 'token-cost' || mode === 'tokens_cost' || mode === 'combined') return 'both';
        return 'flat';
    }

    function currentTokenDepthMode() {
        return normalizeTokenDepthMode(window._tokenDepthMode || (window.WolfBenchUrlState && window.WolfBenchUrlState.state && window.WolfBenchUrlState.state.tokenDepth));
    }

    function compactTokenValue(value) {
        if (!value) return '0';
        if (value >= 1e9) return stripZeros((value / 1e9).toFixed(value >= 10e9 ? 1 : 2)) + 'B';
        if (value >= 1e6) return stripZeros((value / 1e6).toFixed(1)) + 'M';
        if (value >= 1e3) return stripZeros((value / 1e3).toFixed(value >= 100e3 ? 0 : 1)) + 'K';
        return String(Math.round(value));
    }

    function formatCostLabel(value) {
        if (!value || value <= 0) return '';
        return '$' + value.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    }

    function stripZeros(text) {
        return text.replace(/\.0+$/, '').replace(/(\.\d*[1-9])0+$/, '$1');
    }

    function depthForTokens(total) {
        if (!total || total <= 0) return 0;
        return total / tokensPerDepthPixel;
    }

    function depthForCost(cost) {
        if (!cost || cost <= 0) return 0;
        return cost / costPerDepthPixel;
    }

	    function depthScaleLabelForMode(mode) {
	        if (mode === 'tokens') return '3D depth scale: 1 px = 10M tokens · 100 px = 1B tokens';
	        if (mode === 'cost') return '3D depth scale: 1 px = $5 run cost · 100 px = $500';
	        if (mode === 'both') return '3D depth scale: Tokens 1 px = 10M · Cost shadow 1 px = $5';
	        return '';
	    }

    function updateDepthScaleLine(mode) {
        var line = document.getElementById('depthScaleLine');
        if (!line) return;
        var label = depthScaleLabelForMode(mode);
        line.hidden = !label;
        line.textContent = label;
    }

    function toNumber(value) {
        var n = Number.parseFloat(value);
        return Number.isFinite(n) ? n : 0;
    }

    function clamp(value, min, max) {
        return Math.max(min, Math.min(max, value));
    }

    function currentChartUnit() {
        var toggle = document.getElementById('unitToggle');
        return toggle && toggle.getAttribute('data-mode') === 'abs' ? 'abs' : 'pct';
    }

    function currentMetricFilter() {
        var metric = window._filterMetric || '';
        if (!metric && chartArea.classList) {
            baseSegmentOrder.forEach(function(key) {
                if (!metric && chartArea.classList.contains('metric-filter-' + key)) metric = key;
            });
        }
        return metricLabels[metric] ? metric : null;
    }

    function readTokenData(wrapper) {
        var input = toNumber(wrapper.getAttribute('data-token-input'));
        var output = toNumber(wrapper.getAttribute('data-token-output'));
        var total = toNumber(wrapper.getAttribute('data-token-total')) || input + output;
        var cost = toNumber(wrapper.getAttribute('data-cost-total'));
        return {input: input, output: output, total: total, cost: cost};
    }

    function readScores(wrapper, inner) {
        var rounded = {
            solid: toNumber(inner.getAttribute('data-h-solid')),
            worst: toNumber(inner.getAttribute('data-h-worst')),
            average: toNumber(inner.getAttribute('data-h-average')),
            best: toNumber(inner.getAttribute('data-h-best')),
            ceiling: toNumber(inner.getAttribute('data-h-ceiling')) || toNumber(inner.style.height)
        };
        try {
            var raw = JSON.parse(wrapper.getAttribute('data-bar-scores') || '{}');
            var rawCeiling = toNumber(raw.ceiling_raw);
            if (rawCeiling > 0 && rounded.ceiling > 0) {
                var scale = rounded.ceiling / rawCeiling;
                return {
                    solid: toNumber(raw.solid_raw) * scale,
                    worst: toNumber(raw.worst_raw) * scale,
                    average: toNumber(raw.average_raw) * scale,
                    best: toNumber(raw.best_raw) * scale,
                    ceiling: rounded.ceiling
                };
            }
        } catch (err) {}
        return rounded;
    }

	    function metricSegmentElement(inner, key) {
	        if (key === 'worst') return inner.querySelector('.segment-worst') || inner.querySelector('.segment-average') || inner.querySelector('.segment-solid');
	        return inner.querySelector('.segment-' + key);
	    }

    function colorFromSegment(seg, fallback) {
        if (!seg) return fallback;
        var style = window.getComputedStyle(seg);
        var bg = seg.style.backgroundImage || style.backgroundImage || '';
        var colors = bg.match(/rgba?\([^)]+\)|#[0-9a-fA-F]{3,8}/g);
        if (colors && colors.length) return colors[Math.min(colors.length - 1, Math.floor(colors.length * 0.55))];
        var bgColor = seg.style.backgroundColor || style.backgroundColor;
        return bgColor && bgColor !== 'rgba(0, 0, 0, 0)' ? bgColor : fallback;
    }

    function colorFromCss(value, fallback) {
        try {
            return new THREE.Color(value || fallback || '#ffcc33');
        } catch (err) {
            return new THREE.Color(fallback || '#ffcc33');
        }
    }

    function gradientStopsFromSegment(seg, fallback) {
        if (!seg) return [colorFromCss(fallback, '#ffcc33')];
        var style = window.getComputedStyle(seg);
        var bg = seg.style.backgroundImage || style.backgroundImage || '';
        var matches = bg.match(/rgba?\([^)]+\)|#[0-9a-fA-F]{3,8}/g) || [];
        var colors = matches.map(function(value) {
            return colorFromCss(value, fallback);
        });
        if (!colors.length) {
            var bgColor = seg.style.backgroundColor || style.backgroundColor;
            colors.push(colorFromCss(bgColor && bgColor !== 'rgba(0, 0, 0, 0)' ? bgColor : fallback, fallback));
        }
        return colors;
    }

	    function gradientColorAt(stops, t) {
	        if (!stops || !stops.length) return new THREE.Color('#ffcc33');
	        if (stops.length === 1) return stops[0].clone();
	        var scaled = clamp(t, 0, 1) * (stops.length - 1);
        var index = Math.floor(scaled);
        var next = Math.min(stops.length - 1, index + 1);
	        return stops[index].clone().lerp(stops[next], scaled - index);
	    }

	    function colorToCss(color) {
	        var srgb = color.clone().convertLinearToSRGB();
	        return 'rgb(' + Math.round(srgb.r * 255) + ', ' + Math.round(srgb.g * 255) + ', ' + Math.round(srgb.b * 255) + ')';
	    }

	    function gradientCssFromStops(stops) {
	        var stopPositions = [0, 40, 70, 100];
	        return 'linear-gradient(135deg, ' + stops.map(function(color, index) {
	            var position = stopPositions[index] != null ? stopPositions[index] : Math.round((index / Math.max(1, stops.length - 1)) * 100);
	            return colorToCss(color) + ' ' + position + '%';
	        }).join(', ') + ')';
	    }

	    function blendGradientStops(a, b, amount) {
	        var count = Math.max(a.length, b.length, 2);
	        var stops = [];
	        for (var i = 0; i < count; i++) {
	            var t = count === 1 ? 0 : i / (count - 1);
	            stops.push(gradientColorAt(a, t).lerp(gradientColorAt(b, t), amount));
	        }
	        return stops;
	    }

	    function segmentStyleFor(inner, key, fallback) {
	        var element = metricSegmentElement(inner, key);
	        if (key === 'worst') {
	            var solid = inner.querySelector('.segment-solid');
	            var average = inner.querySelector('.segment-average') || solid;
	            var solidStops = gradientStopsFromSegment(solid, fallback);
	            var averageStops = gradientStopsFromSegment(average, fallback);
	            return {
	                background: gradientCssFromStops(blendGradientStops(solidStops, averageStops, 0.55)),
	                boxShadow: average ? window.getComputedStyle(average).boxShadow : '0 0 12px rgba(255,255,255,0.12), inset 0 1px 0 rgba(255,255,255,0.15), inset 0 -1px 0 rgba(0,0,0,0.2)'
	            };
	        }
	        if (!element) {
	            return {
	                background: fallback,
	                boxShadow: '0 0 12px rgba(255,255,255,0.12), inset 0 1px 0 rgba(255,255,255,0.15), inset 0 -1px 0 rgba(0,0,0,0.2)'
	            };
	        }
	        var style = window.getComputedStyle(element);
	        return {
	            background: element.style.background || element.style.backgroundImage || style.backgroundImage || style.backgroundColor || fallback,
	            boxShadow: element.style.boxShadow || style.boxShadow
	        };
	    }

	    function ensureFrontSegment(container, key) {
	        var segment = container.querySelector('.segment-' + key);
	        if (!segment) {
	            segment = document.createElement('div');
	            segment.className = 'segment segment-' + key;
	            segment.setAttribute('data-metric', key);
	            segment.appendChild(document.createElement('div')).className = 'segment-shine';
	        } else if (!segment.querySelector('.segment-shine')) {
	            segment.appendChild(document.createElement('div')).className = 'segment-shine';
	        }
	        return segment;
	    }

	    function readHeightForUnit(element, unit) {
	        return element ? toNumber(element.getAttribute('data-h-' + unit)) : 0;
	    }

	    function captureHtmlSegmentTemplate(inner, fallbackColor) {
	        var container = inner.querySelector('.bar-segments');
	        if (!container) return null;
	        if (container.__wolfBenchSegmentTemplate) return container.__wolfBenchSegmentTemplate;
	        var solid = container.querySelector('.segment-solid');
	        var worst = container.querySelector('.segment-worst');
	        var average = container.querySelector('.segment-average');
	        var best = container.querySelector('.segment-best');
	        var ceiling = container.querySelector('.segment-ceiling');
	        var worstSpacer = container.querySelector('.worst-spacer');
	        var heights = {pct: {}, abs: {}};
	        ['pct', 'abs'].forEach(function(unit) {
	            if (worst) {
	                heights[unit] = {
	                    solid: readHeightForUnit(solid, unit),
	                    worst: readHeightForUnit(worst, unit),
	                    average: readHeightForUnit(average, unit),
	                    best: readHeightForUnit(best, unit),
	                    ceiling: readHeightForUnit(ceiling, unit)
	                };
	                return;
	            }
	            var solidHeight = readHeightForUnit(solid, unit);
	            var worstTop = readHeightForUnit(worstSpacer, unit);
	            var averageHeight = readHeightForUnit(average, unit);
	            var bestHeight = readHeightForUnit(best, unit);
	            var ceilingHeight = readHeightForUnit(ceiling, unit);
	            var averageTop = solidHeight + averageHeight;
	            heights[unit] = {
	                solid: solidHeight,
	                worst: Math.max(0, worstTop - solidHeight),
	                average: Math.max(0, averageTop - worstTop),
	                best: bestHeight,
	                ceiling: ceilingHeight
	            };
	        });
	        var styles = {};
	        baseSegmentOrder.forEach(function(key) {
	            styles[key] = segmentStyleFor(inner, key, fallbackColor);
	        });
	        container.__wolfBenchSegmentTemplate = {heights: heights, styles: styles};
	        return container.__wolfBenchSegmentTemplate;
	    }

	    function syncHtmlFrontSegments(inner, fallbackColor) {
	        var container = inner.querySelector('.bar-segments');
	        if (!container) return;
	        var template = captureHtmlSegmentTemplate(inner, fallbackColor);
	        if (!template) return;
	        var unit = currentChartUnit();
	        var wrapper = inner.closest('.bar-wrapper');
	        var isSingleRun = wrapper && wrapper.getAttribute('data-runs') === '1';
	        var visible = isSingleRun ? ['solid'] : baseSegmentOrder.slice().reverse();
		        var signature = unit + '|' + (isSingleRun ? 'single' : 'stacked') + '|' + visible.map(function(key) {
	            return key + ':' + Math.max(0.5, template.heights[unit][key] || 0).toFixed(1);
	        }).join('|');
	        if (container.getAttribute('data-front-segment-signature') === signature) return;
	        var nodes = visible.map(function(key, index) {
	            var node = ensureFrontSegment(container, key);
	            var pctHeight = Math.max(0.5, template.heights.pct[key] || 0);
	            var absHeight = Math.max(0.5, template.heights.abs[key] || 0);
	            var height = unit === 'abs' ? absHeight : pctHeight;
	            node.className = 'segment segment-' + key;
	            node.setAttribute('data-metric', key);
	            node.setAttribute('data-h-pct', pctHeight.toFixed(1));
	            node.setAttribute('data-h-abs', absHeight.toFixed(1));
	            node.style.height = height.toFixed(1) + 'px';
	            node.style.background = template.styles[key].background;
	            node.style.boxShadow = template.styles[key].boxShadow;
	            node.style.display = 'flex';
	            node.style.borderBottomColor = index === visible.length - 1 ? 'transparent' : 'rgba(0,0,0,0.2)';
	            node.style.borderRadius = index === 0
	                ? '8px 8px 0 0'
	                : (index === visible.length - 1 ? '0 0 4px 4px' : '0');
	            return node;
	        });
	        container.replaceChildren.apply(container, nodes);
	        container.setAttribute('data-front-segment-signature', signature);
	    }

	    function syncHtmlFrontSegmentsForVisibleBars() {
	        Array.prototype.slice.call(chartArea.querySelectorAll('.bar-wrapper')).forEach(function(wrapper) {
	            if (wrapper.offsetParent === null || wrapper.classList.contains('agent-hidden') || wrapper.classList.contains('bar-dismissed')) return;
	            var inner = wrapper.querySelector('.bar-inner');
	            if (!inner || inner.offsetParent === null) return;
	            var label = wrapper.querySelector('.bar-top-label');
	            var fallbackColor = label ? window.getComputedStyle(label).color : 'rgb(255,204,51)';
	            syncHtmlFrontSegments(inner, fallbackColor);
	        });
	    }

    function queueRenderAfterLayoutSettle() {
        if (settleQueued) return;
        settleQueued = true;
        window.requestAnimationFrame(function() {
            window.requestAnimationFrame(function() {
                settleQueued = false;
                queueRender();
            });
        });
    }

	    function syncLabelsToSegments(inner, segments) {
	        var tops = {};
	        segments.forEach(function(segment) {
	            tops[segment.key] = segment.top;
	        });
	        inner.querySelectorAll('.seg-label').forEach(function(label) {
	            var metric = label.getAttribute('data-metric');
	            if (tops[metric] != null) label.style.bottom = tops[metric].toFixed(1) + 'px';
	        });
	    }

	    function vertexGradientColor(point, z, width, height, depth, stops, outputPart, faceKind) {
	        var px = width ? clamp(point.x / width, 0, 1) : 0;
	        var py = height ? clamp(point.y / height, 0, 1) : 0;
	        var pz = depth ? clamp(z / depth, 0, 1) : 0;
	        var vertical = 1 - py;
	        var t = clamp(0.10 + (px * 0.32 + vertical * 0.68) * 0.82, 0, 1);
	        var color = gradientColorAt(stops, t);
	        if (faceKind === 'front') {
	            var hsl = {};
	            color.getHSL(hsl);
	            hsl.s = clamp(hsl.s * 1.08, 0, 1);
	            hsl.l = clamp(0.5 + (hsl.l - 0.5) * 1.10, 0.055, 0.965);
	            color.setHSL(hsl.h, hsl.s, hsl.l);
	            var shine = Math.max(0, 1 - Math.abs(px - 0.24) / 0.16);
	            var softGloss = Math.max(0, 1 - Math.abs(px - 0.48) / 0.62);
	            var rightShadow = clamp((px - 0.70) / 0.30, 0, 1);
	            var bottomLip = clamp((0.07 - py) / 0.07, 0, 1);
	            color.lerp(new THREE.Color(0xffffff), shine * 0.14 + softGloss * 0.025);
	            color.lerp(new THREE.Color(0x050809), rightShadow * 0.12 + bottomLip * 0.045);
	        } else {
	            var depthShade = 0.050 + pz * 0.052 + (outputPart ? 0.022 : 0);
	            color.multiplyScalar(1 - depthShade);
	            color.lerp(new THREE.Color(0xffffff), vertical * 0.010);
	        }
	        if (outputPart) color.multiplyScalar(0.99);
	        return color;
	    }

	    function frontShineMaterial(opacity) {
	        var cacheKey = 'front-shine|' + opacity;
	        if (materials.has(cacheKey)) return materials.get(cacheKey);
	        var material = new THREE.MeshBasicMaterial({
	            color: 0xffffff,
	            transparent: true,
	            opacity: opacity,
		            side: THREE.DoubleSide,
	            depthTest: false,
		            depthWrite: false
	        });
	        material.toneMapped = false;
	        materials.set(cacheKey, material);
	        return material;
	    }

    function shadeColor(base, key, outputPart) {
        var color = base.clone();
        var hsl = {};
        color.getHSL(hsl);
        var light = {
            solid: 0.47,
            worst: 0.58,
            average: 0.68,
            best: 0.78,
            ceiling: 0.86
        }[key] || 0.74;
        hsl.s = clamp(hsl.s * (outputPart ? 0.88 : 1.08), 0, 1);
        hsl.l = clamp(hsl.l * light + (outputPart ? -0.04 : 0), 0.08, 0.82);
        color.setHSL(hsl.h, hsl.s, hsl.l);
        if (outputPart) color.lerp(new THREE.Color(0x151a20), 0.14);
        return color;
    }

    function materialFor(color, key, outputPart) {
        var cacheKey = color.getHexString() + '|' + key + '|' + (outputPart ? 'out' : 'in');
        if (materials.has(cacheKey)) return materials.get(cacheKey);
	        var material = new THREE.MeshBasicMaterial({
	            color: 0xffffff,
	            vertexColors: true,
	            transparent: false,
	            opacity: 1,
	            side: THREE.DoubleSide,
            depthTest: true,
            depthWrite: true
        });
        material.toneMapped = false;
        materials.set(cacheKey, material);
        return material;
    }

    function costShadowGradientStops() {
        return [
            new THREE.Color(0x5f6670),
            new THREE.Color(0xa7adb5),
            new THREE.Color(0x4c535c)
        ];
    }

    function costShadowMaterialFor(key, opacity) {
        var cacheKey = 'cost-shadow|' + key + '|' + opacity;
        if (materials.has(cacheKey)) return materials.get(cacheKey);
	        var material = new THREE.MeshBasicMaterial({
	            color: 0xffffff,
	            vertexColors: true,
	            transparent: true,
	            opacity: opacity,
	            side: THREE.DoubleSide,
	            depthTest: true,
		            depthWrite: true
	        });
        material.toneMapped = false;
        materials.set(cacheKey, material);
        return material;
    }

    function roundedRectShape(width, height, radii) {
        radii = radii || {};
        var tl = clamp(radii.tl || 0, 0, Math.min(width, height) * 0.5);
        var tr = clamp(radii.tr || 0, 0, Math.min(width, height) * 0.5);
        var br = clamp(radii.br || 0, 0, Math.min(width, height) * 0.5);
        var bl = clamp(radii.bl || 0, 0, Math.min(width, height) * 0.5);
        var shape = new THREE.Shape();
        shape.moveTo(bl, 0);
        shape.lineTo(width - br, 0);
        if (br) shape.quadraticCurveTo(width, 0, width, br);
        else shape.lineTo(width, 0);
        shape.lineTo(width, height - tr);
        if (tr) shape.quadraticCurveTo(width, height, width - tr, height);
        else shape.lineTo(width, height);
        shape.lineTo(tl, height);
        if (tl) shape.quadraticCurveTo(0, height, 0, height - tl);
        else shape.lineTo(0, height);
        shape.lineTo(0, bl);
        if (bl) shape.quadraticCurveTo(0, 0, bl, 0);
        else shape.lineTo(0, 0);
        return shape;
    }

    function pushPoint(points, x, y) {
        var last = points[points.length - 1];
        if (last && Math.abs(last.x - x) < 0.01 && Math.abs(last.y - y) < 0.01) return;
        points.push(new THREE.Vector2(x, y));
    }

    function pushArc(points, cx, cy, radius, start, end, segments) {
        if (!radius) return;
        for (var i = 1; i <= segments; i++) {
            var t = start + (end - start) * (i / segments);
            pushPoint(points, cx + Math.cos(t) * radius, cy + Math.sin(t) * radius);
        }
    }

    function roundedRectPoints(width, height, radii) {
        radii = radii || {};
        var tl = clamp(radii.tl || 0, 0, Math.min(width, height) * 0.5);
        var tr = clamp(radii.tr || 0, 0, Math.min(width, height) * 0.5);
        var br = clamp(radii.br || 0, 0, Math.min(width, height) * 0.5);
        var bl = clamp(radii.bl || 0, 0, Math.min(width, height) * 0.5);
        var points = [];
        pushPoint(points, bl, 0);
        pushPoint(points, width - br, 0);
        pushArc(points, width - br, br, br, -Math.PI / 2, 0, 6);
        pushPoint(points, width, height - tr);
        pushArc(points, width - tr, height - tr, tr, 0, Math.PI / 2, 6);
        pushPoint(points, tl, height);
        pushArc(points, tl, height - tl, tl, Math.PI / 2, Math.PI, 6);
        pushPoint(points, 0, bl);
        pushArc(points, bl, bl, bl, Math.PI, Math.PI * 1.5, 6);
        return points;
    }

    function includeDepthEdge(a, b, width, height, radii) {
        var topRadius = Math.max(radii.tl || 0, radii.tr || 0);
        var bottomRadius = Math.max(radii.bl || 0, radii.br || 0);
        var maxY = Math.max(a.y, b.y);
        var minY = Math.min(a.y, b.y);
        var topEdge = topRadius > 0 && maxY > height - topRadius - 0.05;
        var bottomEdge = bottomRadius > 0 && minY < bottomRadius + 0.05;
        if (topEdge) return true;
        if (bottomEdge) return true;
        var leftEdge = Math.max(a.x, b.x) < 0.05;
        var rightEdge = Math.min(a.x, b.x) > width - 0.05;
        if (leftEdge || rightEdge) return true;
        return false;
    }

	    function createSegmentGeometry(width, height, depth, zStart, radii, showFrontCap, gradientStops, outputPart) {
	        radii = radii || {};
	        var points = roundedRectPoints(width, height, radii);
        var triangles = THREE.ShapeUtils.triangulateShape(points, []);
        var positions = [];
        var colors = [];
        function vertex(point, z, faceKind) {
            positions.push(point.x, point.y, z);
            var color = vertexGradientColor(point, z, width, height, depth, gradientStops, outputPart, faceKind);
            colors.push(color.r, color.g, color.b);
        }
        if (showFrontCap) {
            triangles.forEach(function(face) {
                vertex(points[face[0]], 0, 'front');
                vertex(points[face[1]], 0, 'front');
                vertex(points[face[2]], 0, 'front');
            });
        }
        for (var i = 0; i < points.length; i++) {
            var next = (i + 1) % points.length;
            var a = points[i];
            var b = points[next];
            if (!includeDepthEdge(a, b, width, height, radii)) continue;
            vertex(a, 0, 'side');
            vertex(b, 0, 'side');
            vertex(b, depth, 'side');
            vertex(a, 0, 'side');
            vertex(b, depth, 'side');
            vertex(a, depth, 'side');
        }
        var geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
        geometry.translate(0, 0, zStart || 0);
        geometry.applyMatrix4(shearMatrix);
	        geometry.computeVertexNormals();
	        return geometry;
	    }

	    function createFrontStripGeometry(width, height, left, stripWidth) {
	        var right = left + stripWidth;
	        var geometry = new THREE.BufferGeometry();
	        geometry.setAttribute('position', new THREE.Float32BufferAttribute([
	            left, 0, 0,
	            right, 0, 0,
	            right, height, 0,
	            left, 0, 0,
	            right, height, 0,
	            left, height, 0
	        ], 3));
	        geometry.applyMatrix4(shearMatrix);
	        return geometry;
	    }

	    function clearDepthLabels() {
	        if (!labelLayer) return;
	        labelLayer.replaceChildren();
	    }

	    function depthLabelText(token, mode) {
	        if (mode === 'cost' || mode === 'cost-shadow') return formatCostLabel(token.cost);
	        if (!token.total || token.total <= 0) return '';
	        return compactTokenValue(token.total);
	    }

	    function addDepthLabel(x, screenBottom, width, visualDepth, token, mode, options) {
	        if (!labelLayer) return null;
	        options = options || {};
	        var text = depthLabelText(token, mode);
	        if (!text) return null;
	        var label = document.createElement('div');
	        label.className = 'three-bars-depth-label';
	        label.textContent = text;
	        label.setAttribute('data-depth-mode', mode);
	        labelLayer.appendChild(label);
	        var projectedY = visualDepth * projectY / projectX;
	        var depthEdgeLength = Math.sqrt(visualDepth * visualDepth + projectedY * projectedY);
	        var labelWidth = label.offsetWidth || 0;
	        var depthFitPadding = 2;
	        var forcedOrientation = options.orientation || '';
	        var fitsDepthEdge = forcedOrientation === 'edge'
	            ? true
	            : (forcedOrientation === 'vertical' ? false : labelWidth + depthFitPadding <= depthEdgeLength);
	        var yOffset = Number.isFinite(options.yOffset) ? options.yOffset : 0;
	        label.setAttribute('data-depth-orientation', fitsDepthEdge ? 'edge' : 'vertical');
	        if (fitsDepthEdge) {
	            label.style.left = (x + width + 5).toFixed(1) + 'px';
	            label.style.top = (screenBottom - 20 + yOffset).toFixed(1) + 'px';
	            label.style.transform = 'rotate(' + depthLabelAngle.toFixed(2) + 'deg)';
	        } else {
	            label.style.left = (x + width + Math.max(5, Math.min(10, visualDepth * 0.25 + 5))).toFixed(1) + 'px';
	            label.style.top = (screenBottom - 20 + yOffset).toFixed(1) + 'px';
	            label.style.transform = 'rotate(-90deg)';
	        }
	        var layerRect = labelLayer.getBoundingClientRect();
	        var labelRect = label.getBoundingClientRect();
	        return {
	            right: labelRect.right - layerRect.left,
	            bottom: labelRect.bottom - layerRect.top
	        };
	    }

    function disposeObject(object) {
        object.traverse(function(child) {
            if (child.geometry) child.geometry.dispose();
        });
    }

    function setupRenderer(width, height) {
        if (!renderer) {
            canvas = document.createElement('canvas');
            canvas.className = 'three-bars-canvas';
            chartArea.insertBefore(canvas, chartArea.firstChild);
            labelLayer = document.createElement('div');
            labelLayer.className = 'three-bars-depth-label-layer';
            chartArea.insertBefore(labelLayer, canvas.nextSibling);
            renderer = new THREE.WebGLRenderer({canvas: canvas, alpha: true, antialias: true, preserveDrawingBuffer: true, powerPreference: 'high-performance'});
            renderer.outputColorSpace = THREE.SRGBColorSpace;
	            renderer.toneMapping = THREE.NoToneMapping;
	            renderer.toneMappingExposure = 1;
            scene = new THREE.Scene();
            camera = new THREE.OrthographicCamera(0, width, height, 0, -8000, 8000);
            camera.position.set(0, 0, 3000);
            camera.lookAt(0, 0, 0);
            camera.updateProjectionMatrix();
            root = new THREE.Group();
            scene.add(root);
            var ambient = new THREE.HemisphereLight(0xf5fff9, 0x111820, 1.35);
            scene.add(ambient);
            var key = new THREE.DirectionalLight(0xffffff, 2.45);
            key.position.set(-360, 840, 1200);
            scene.add(key);
            var rim = new THREE.DirectionalLight(0x8fc7ff, 0.42);
            rim.position.set(720, 120, 640);
            scene.add(rim);
        }
        var dpr = Math.min(window.devicePixelRatio || 1, 2);
        renderer.setPixelRatio(dpr);
        renderer.setSize(width, height, false);
        canvas.style.width = width + 'px';
        canvas.style.height = height + 'px';
        if (labelLayer) {
            labelLayer.style.width = width + 'px';
            labelLayer.style.height = height + 'px';
        }
        camera.left = 0;
        camera.right = width;
        camera.top = height;
        camera.bottom = 0;
        camera.updateProjectionMatrix();
    }

    function chartLayoutWidth() {
        var rect = chartArea.getBoundingClientRect();
        var style = window.getComputedStyle(chartArea);
        var minWidth = parseFloat(style.minWidth) || 0;
        var styleWidth = parseFloat(style.width) || 0;
        var modelsRow = chartArea.querySelector('.models-row');
        var rowWidth = modelsRow ? modelsRow.scrollWidth : 0;
        return Math.max(1, Math.ceil(Math.max(rect.width, styleWidth, minWidth, rowWidth, chartArea.offsetWidth || 0)));
    }

    function setChartArea3DWidth(width) {
        if (!width || width <= 1) return;
        chartArea.style.minWidth = Math.ceil(width) + 'px';
    }

    function clearRoot() {
        if (!root) return;
        while (root.children.length) {
            var child = root.children.pop();
            disposeObject(child);
            root.remove(child);
        }
    }

    function buildSegments(scores, totalHeight, isSingleRun) {
        if (isSingleRun) {
            var singleTop = clamp(scores.ceiling || scores.average || scores.solid || 0, 0, totalHeight);
            return singleTop > 1.1 ? [{key: 'solid', bottom: 0, top: singleTop}] : [];
        }
        var bounds = {
            solid: clamp(scores.solid, 0, totalHeight),
            worst: clamp(Math.max(scores.worst, scores.solid), 0, totalHeight),
            average: clamp(Math.max(scores.average, scores.worst, scores.solid), 0, totalHeight),
            best: clamp(Math.max(scores.best, scores.average, scores.worst, scores.solid), 0, totalHeight),
            ceiling: clamp(Math.max(scores.ceiling, scores.best, scores.average, scores.worst, scores.solid), 0, totalHeight)
        };
        var ranges = [
            {key: 'solid', bottom: 0, top: bounds.solid},
            {key: 'worst', bottom: bounds.solid, top: bounds.worst},
            {key: 'average', bottom: bounds.worst, top: bounds.average},
            {key: 'best', bottom: bounds.average, top: bounds.best},
            {key: 'ceiling', bottom: bounds.best, top: bounds.ceiling}
        ];
        return ranges.filter(function(seg) { return seg.top - seg.bottom > 1.1; });
    }

    function buildMetricFilteredSegments(scores, totalHeight, metric, isSingleRun) {
        if (!metric) return buildSegments(scores, totalHeight, isSingleRun);
        var top = clamp(scores[metric] || 0, 0, totalHeight);
        if (top <= 1.1) return [];
        return [{key: metric, bottom: 0, top: top, filtered: true}];
    }

	    function addSegmentMesh(x, y, width, height, zStart, depth, color, gradientStops, key, outputPart, meta, radii, showFrontCap) {
	        if (depth <= 0.4 || height <= 0.7) return;
	        var geometry = createSegmentGeometry(width, height, depth, zStart, radii || {}, !!showFrontCap, gradientStops, outputPart);
	        var material = materialFor(color, key, outputPart);
        var mesh = new THREE.Mesh(geometry, material);
        mesh.position.set(x, y, 0);
        mesh.castShadow = false;
	        mesh.receiveShadow = false;
	        mesh.userData = meta;
	        root.add(mesh);
	        if (showFrontCap && !outputPart) {
	            [
	                {left: width * 0.115, stripWidth: width * 0.28, opacity: 0.028},
	                {left: width * 0.220, stripWidth: width * 0.055, opacity: 0.046}
	            ].forEach(function(shine) {
	                var shineGeometry = createFrontStripGeometry(width, height, shine.left, shine.stripWidth);
	                var shineMesh = new THREE.Mesh(shineGeometry, frontShineMaterial(shine.opacity));
	                shineMesh.position.set(x, y, 0);
	                shineMesh.renderOrder = 30;
	                root.add(shineMesh);
	            });
	        }
	    }

	    function roundedPolygonPoints(vertices, radii) {
	        var points = [];
	        function pushRoundedPoint(x, y) {
	            var last = points[points.length - 1];
	            if (last && Math.abs(last.x - x) < 0.01 && Math.abs(last.y - y) < 0.01) return;
	            points.push(new THREE.Vector2(x, y));
	        }
	        vertices.forEach(function(vertex, index) {
	            var prev = vertices[(index - 1 + vertices.length) % vertices.length];
	            var next = vertices[(index + 1) % vertices.length];
	            var radius = radii[index] || 0;
	            var prevVector = new THREE.Vector2(prev.x - vertex.x, prev.y - vertex.y);
	            var nextVector = new THREE.Vector2(next.x - vertex.x, next.y - vertex.y);
	            var prevLength = prevVector.length();
	            var nextLength = nextVector.length();
	            if (radius <= 0.01 || prevLength <= 0.01 || nextLength <= 0.01) {
	                pushRoundedPoint(vertex.x, vertex.y);
	                return;
	            }
	            var distance = Math.min(radius, prevLength * 0.48, nextLength * 0.48);
	            var start = new THREE.Vector2(vertex.x, vertex.y).add(prevVector.normalize().multiplyScalar(distance));
	            var end = new THREE.Vector2(vertex.x, vertex.y).add(nextVector.normalize().multiplyScalar(distance));
	            pushRoundedPoint(start.x, start.y);
	            for (var step = 1; step <= 5; step++) {
	                var t = step / 5;
	                var inv = 1 - t;
	                var x = inv * inv * start.x + 2 * inv * t * vertex.x + t * t * end.x;
	                var y = inv * inv * start.y + 2 * inv * t * vertex.y + t * t * end.y;
	                pushRoundedPoint(x, y);
	            }
	        });
	        return points;
	    }

	    function createCostShadowGeometry(width, height, depth, zStart, radii) {
	        var dx = depth * projectX;
	        var dy = depth * projectY;
	        var z = -projectZ * (zStart || 0);
	        radii = radii || {};
	        var shadowRadii = [
	            radii.bl || 0,
	            (radii.br || 0) * 0.65,
	            radii.br || 0,
	            radii.tr || 0,
	            radii.tl || 0,
	            (radii.tl || 0) * 0.65
	        ];
	        var points = roundedPolygonPoints([
	            {x: 0, y: 0},
	            {x: width, y: 0},
	            {x: width + dx, y: dy},
	            {x: width + dx, y: height + dy},
	            {x: dx, y: height + dy},
	            {x: 0, y: height}
	        ], shadowRadii);
	        var triangles = THREE.ShapeUtils.triangulateShape(points, []);
		        var positions = [];
		        var colors = [];
		        var stops = costShadowGradientStops();
		        var spanWidth = Math.max(width + Math.abs(dx), 1);
		        var spanHeight = Math.max(height + Math.abs(dy), 1);
		        function vertex(point) {
		            positions.push(point.x, point.y, z);
		            var px = clamp(point.x / spanWidth, 0, 1);
		            var py = clamp(point.y / spanHeight, 0, 1);
		            var color = gradientColorAt(stops, clamp(0.08 + (px * 0.35 + (1 - py) * 0.65) * 0.84, 0, 1));
		            color.multiplyScalar(0.88);
		            colors.push(color.r, color.g, color.b);
		        }
		        triangles.forEach(function(face) {
		            vertex(points[face[0]]);
		            vertex(points[face[1]]);
		            vertex(points[face[2]]);
		        });
		        var geometry = new THREE.BufferGeometry();
		        geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
		        geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
		        return geometry;
		    }

	    function addCostShadowMesh(x, y, width, height, depth, key, meta, radii, zStart) {
	        if (depth <= 0.4 || height <= 0.7) return;
	        var geometry = createCostShadowGeometry(width, height, depth, zStart || 0, radii || {});
	        var material = costShadowMaterialFor(key, 0.46);
	        var mesh = new THREE.Mesh(geometry, material);
	        mesh.position.set(x, y, 0);
	        mesh.castShadow = false;
	        mesh.receiveShadow = false;
	        mesh.renderOrder = 4;
	        mesh.userData = meta;
	        root.add(mesh);
	    }

    function updateLegend(mode) {
        var toggle = document.getElementById('svgIsoLegend');
        if (!toggle) {
            updateDepthScaleLine(mode);
            return;
        }
        var label = toggle.querySelector('.svg-iso-label');
        toggle.classList.toggle('active', mode !== 'flat');
        toggle.classList.toggle('dimmed', mode === 'flat');
        toggle.setAttribute('data-token-depth', mode);
        toggle.setAttribute('aria-label', mode === 'flat' ? 'Bar mode: 2D' : 'Bar mode: 3D ' + mode);
        if (mode === 'flat') {
            if (label) label.textContent = 'Bars: 2D';
            toggle.title = 'Bars are in 2D. Click for 3D: Tokens.';
        } else if (mode === 'tokens') {
            if (label) label.textContent = 'Bars: 3D Tokens';
            toggle.title = 'Three.js stacked 3D bars with tighter reserved spacing. Depth is uncapped absolute linear token volume: 1px = 10M tokens. Front depth is input, rear depth is output. Click for 3D Cost.';
        } else if (mode === 'cost') {
            if (label) label.textContent = 'Bars: 3D Cost';
            toggle.title = 'Three.js stacked 3D bars with tighter reserved spacing. Depth is uncapped absolute linear run cost: 1px = $5. No log scale, no per-chart normalization. Click for 3D Tokens + Cost.';
        } else {
            if (label) label.textContent = 'Bars: 3D Tokens + Cost';
            toggle.title = 'Main bar uses token depth; the neutral gray shadow uses run cost. Click for 2D bars.';
        }
        updateDepthScaleLine(mode);
    }

    function renderThreeBars() {
        var mode = currentTokenDepthMode();
        updateLegend(mode);
        if (mode === 'flat') {
            if (window.updateChartWidth) window.updateChartWidth();
            syncHtmlFrontSegmentsForVisibleBars();
            if (window.WolfBenchApplyCurrentUnit) window.WolfBenchApplyCurrentUnit();
            chartArea.classList.remove('three-bars-ready');
            if (canvas) canvas.style.display = 'none';
            clearDepthLabels();
            clearRoot();
            return;
        }
        var width = chartLayoutWidth();
        var height = chartArea.offsetHeight;
        setupRenderer(width, height);
        canvas.style.display = 'block';
        clearRoot();
        clearDepthLabels();
	        var activeMetric = currentMetricFilter();
	        var areaRect = chartArea.getBoundingClientRect();
	        var wrappers = Array.prototype.slice.call(chartArea.querySelectorAll('.bar-wrapper'));
	        var requiredRight = width;
	        wrappers.forEach(function(wrapper) {
            if (wrapper.offsetParent === null || wrapper.classList.contains('agent-hidden') || wrapper.classList.contains('bar-dismissed')) return;
            var inner = wrapper.querySelector('.bar-inner');
            var bar = wrapper.querySelector('.bar');
            if (!inner || !bar || inner.offsetParent === null) return;
            var rect = inner.getBoundingClientRect();
            if (!rect.width || !rect.height) return;
            var token = readTokenData(wrapper);
            var usingCostDepth = mode === 'cost';
            var usingBothDepth = mode === 'both';
            var hasTokenData = token.total > 0;
            var hasCostData = token.cost > 0;
            var depth = usingCostDepth
                ? (hasCostData ? depthForCost(token.cost) : missingDepth)
                : (hasTokenData ? depthForTokens(token.total) : missingDepth);
            if (!depth) return;
            var costDepth = usingBothDepth && hasCostData ? depthForCost(token.cost) : 0;
            var visualDepth = Math.max(2, depth * projectX);
            var costVisualDepth = costDepth ? Math.max(2, costDepth * projectX) : 0;
            var costShadowOffsetX = usingBothDepth ? Math.max(5, Math.min(8, rect.width * 0.11)) : 0;
	            var costShadowOffsetY = usingBothDepth ? -4 : 0;
            var rightExtent = Math.max(visualDepth, costDepth ? costShadowOffsetX + costVisualDepth : 0);
            var rowGap = wrapper.parentElement ? Number.parseFloat(window.getComputedStyle(wrapper.parentElement).columnGap || window.getComputedStyle(wrapper.parentElement).gap) || 0 : 0;
            var projectedDepth = visualDepth;
            var spacingReserve = Math.max(0, rightExtent + spacedVisualGap - rowGap);
            wrapper.style.setProperty('--iso-depth', projectedDepth.toFixed(1) + 'px');
            wrapper.style.setProperty('--iso-visual-depth', visualDepth.toFixed(1) + 'px');
            wrapper.style.setProperty('--iso-spacing', spacingReserve.toFixed(1) + 'px');
            bar.style.setProperty('--iso-depth', projectedDepth.toFixed(1) + 'px');
            bar.style.setProperty('--iso-visual-depth', visualDepth.toFixed(1) + 'px');
            bar.style.setProperty('--iso-spacing', spacingReserve.toFixed(1) + 'px');
	            var scores = readScores(wrapper, inner);
	            var isSingleRun = wrapper.getAttribute('data-runs') === '1';
	            var segments = buildMetricFilteredSegments(scores, rect.height, activeMetric, isSingleRun);
	            if (!segments.length) return;
	            var label = wrapper.querySelector('.bar-top-label');
            var fallbackColor = label ? window.getComputedStyle(label).color : 'rgb(255,204,51)';
            syncHtmlFrontSegments(inner, fallbackColor);
            syncLabelsToSegments(inner, segments);
            var inputShare = !usingCostDepth && hasTokenData ? clamp(token.input / token.total, 0, 1) : 1;
            var inputDepth = usingCostDepth ? depth : depth * inputShare;
            var outputDepth = usingCostDepth ? 0 : Math.max(0, depth - inputDepth);
            var outputStart = inputDepth + (outputDepth > 1.5 ? tokenGap : 0);
            var outputActualDepth = Math.max(0, outputDepth - (outputDepth > 1.5 ? tokenGap : 0));
            var x = rect.left - areaRect.left;
            var screenBottom = (rect.top - areaRect.top) + rect.height;
            var bottomY = height - ((rect.top - areaRect.top) + rect.height);
			            var tokenLabelBounds = addDepthLabel(
			                x,
			                screenBottom,
			                rect.width,
			                visualDepth,
			                token,
			                usingBothDepth ? 'tokens' : mode,
			                usingBothDepth ? {orientation: 'vertical', yOffset: -13} : null
			            );
			            if (tokenLabelBounds) requiredRight = Math.max(requiredRight, tokenLabelBounds.right + 12);
			            if (usingBothDepth && costDepth) {
			                var costLabelBounds = addDepthLabel(x + costShadowOffsetX, screenBottom - costShadowOffsetY, rect.width, costVisualDepth, token, 'cost-shadow', {orientation: 'edge'});
			                if (costLabelBounds) requiredRight = Math.max(requiredRight, costLabelBounds.right + 12);
			            }
		            if (usingBothDepth && costDepth) {
		                var shadowBottom = segments.reduce(function(min, segment) { return Math.min(min, segment.bottom); }, Number.POSITIVE_INFINITY);
		                var shadowTop = segments.reduce(function(max, segment) { return Math.max(max, segment.top); }, 0);
		                if (Number.isFinite(shadowBottom) && shadowTop - shadowBottom > 1.1) {
		                    var shadowHeight = Math.max(0.5, shadowTop - shadowBottom - segmentGap);
		                    var shadowY = bottomY + shadowBottom + segmentGap * 0.5;
		                    var shadowOuterRadius = Math.min(7.5, rect.width * 0.18, shadowHeight * 0.28);
		                    var shadowRadii = {
		                        tl: shadowOuterRadius,
		                        tr: shadowOuterRadius,
		                        br: Math.min(4.5, shadowOuterRadius),
		                        bl: Math.min(4.5, shadowOuterRadius)
		                    };
		                    var shadowMeta = {
		                        agent: wrapper.getAttribute('data-agent') || '',
		                        metric: 'cost-shadow',
		                        metricLabel: 'Run cost',
		                        depthMode: 'cost-shadow',
		                        costUsd: token.cost,
		                        inputTokens: token.input,
		                        outputTokens: token.output,
		                        totalTokens: token.total
		                    };
			                    var shadowZStart = depth + 1;
				                    addCostShadowMesh(
					                        x + costShadowOffsetX,
					                        shadowY + costShadowOffsetY,
			                        rect.width,
			                        shadowHeight,
			                        costDepth,
			                        'cost-shadow',
			                        shadowMeta,
			                        shadowRadii,
			                        shadowZStart
			                    );
			                    requiredRight = Math.max(requiredRight, x + costShadowOffsetX + rect.width + costVisualDepth + 12);
			                }
			            }
		            segments.forEach(function(segment, segmentIndex) {
	                var segHeight = segment.top - segment.bottom;
	                var displayHeight = Math.max(0.5, segHeight - segmentGap);
	                var y = bottomY + segment.bottom + segmentGap * 0.5;
	                var segmentElement = metricSegmentElement(inner, segment.key);
	                var baseColor = colorFromCss(colorFromSegment(segmentElement, fallbackColor), fallbackColor);
	                var gradientStops = gradientStopsFromSegment(segmentElement, fallbackColor);
	                var isBottom = segmentIndex === 0;
	                var isTop = segmentIndex === segments.length - 1;
	                var outerRadius = Math.min(7.5, rect.width * 0.18, displayHeight * 0.28);
                var radii = {
                    tl: isTop ? outerRadius : 0,
                    tr: isTop ? outerRadius : 0,
                    br: isBottom ? Math.min(4.5, outerRadius) : 0,
                    bl: isBottom ? Math.min(4.5, outerRadius) : 0
                };
	                var meta = {
	                    agent: wrapper.getAttribute('data-agent') || '',
	                    metric: segment.key,
	                    metricLabel: metricLabels[segment.key],
	                    depthMode: usingCostDepth ? 'cost' : 'tokens',
	                    costUsd: token.cost,
	                    inputTokens: token.input,
		                    outputTokens: token.output,
		                    totalTokens: token.total
		                };
		                var inputHasFront = inputDepth > 0.4;
			                addSegmentMesh(x, y, rect.width, displayHeight, 0, inputDepth, baseColor, gradientStops, segment.key, false, meta, radii, true);
			                addSegmentMesh(x, y, rect.width, displayHeight, outputStart, outputActualDepth, baseColor, gradientStops, segment.key, true, meta, radii, !inputHasFront);
		            });
	        });
	        var settledWidth = chartLayoutWidth();
	        var requiredWidth = Math.ceil(Math.max(settledWidth, requiredRight));
	        if (requiredWidth > width + 2) {
	            setChartArea3DWidth(requiredWidth);
	            chartArea.classList.remove('three-bars-ready');
	            clearRoot();
	            clearDepthLabels();
	            queueRenderAfterLayoutSettle();
	            return;
	        }
	        setChartArea3DWidth(Math.max(width, requiredWidth));
	        renderer.render(scene, camera);
	        chartArea.classList.add('three-bars-ready');
        if (window.WolfBenchRefreshModelHighlights && chartArea.querySelector('.model-group.model-highlighted')) {
            window.requestAnimationFrame(window.WolfBenchRefreshModelHighlights);
        }
    }

    function queueRender() {
        if (queued) return;
        queued = true;
        window.requestAnimationFrame(function() {
            queued = false;
            renderThreeBars();
        });
    }

    window.WolfBenchThreeBars = {
        render: queueRender,
        renderNow: renderThreeBars,
        modes: tokenDepthModes,
	        scale: {
		            tokensPerDepthPixel: tokensPerDepthPixel,
		            costPerDepthPixel: costPerDepthPixel,
            missingDepth: missingDepth,
            projectX: projectX,
            projectY: projectY
        }
    };
    renderThreeBars();
    document.addEventListener('wolfbench:token-depth-change', queueRender);
    window.addEventListener('resize', queueRender);
    document.addEventListener('click', function(event) {
        if (event.target.closest('.legend-metric, .legend-agent, .model-btn, #unitToggle, #barSortToggle, #modelVisToggle, #svgIsoLegend')) queueRender();
    }, true);
    new MutationObserver(queueRender).observe(chartArea, {subtree: true, attributes: true, attributeFilter: ['class', 'style']});
})();
