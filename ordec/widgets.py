# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import anywidget
import traitlets


class ConfettiWidget(anywidget.AnyWidget):
    _esm = """
    import confetti from "https://esm.sh/canvas-confetti@1.6.0";
    
    function render({ model, el }) {
      const btn = document.createElement('button');
      btn.innerText = '🎉 Celebrate!';
      btn.style.padding = '10px 20px';
      btn.style.fontSize = '16px';
      btn.style.borderRadius = '8px';
      btn.style.border = '2px solid #ddd';
      btn.style.cursor = 'pointer';
      
      btn.addEventListener('click', () => {
        // Fire confetti from the center
        confetti({
          particleCount: 100,
          spread: 70,
          origin: { y: 0.6 }
        });
        
        // Fire from the left and right after a small delay
        setTimeout(() => {
          confetti({
            particleCount: 50,
            spread: 60,
            angle: 60,
            origin: { x: 0 }
          });
          confetti({
            particleCount: 50,
            spread: 60,
            angle: 120,
            origin: { x: 1 }
          });
        }, 250);
      });
      
      el.appendChild(btn);
    }
    export default { render };
    """


celebrate = ConfettiWidget()


class TextAreaWidget(anywidget.AnyWidget):
    # Widget front-end JavaScript code
    _esm = """
    function render({ model, el }) {
      let textarea = document.createElement("textarea");
      textarea.value = model.get("text");
      textarea.style.width = "300px";
      textarea.style.height = "150px";
      
      textarea.addEventListener("input", () => {
        model.set("text", textarea.value);
        model.save_changes();
      });
      
      model.on("change:text", () => {
        textarea.value = model.get("text");
      });
      
      let counter = document.createElement("div");
      counter.innerHTML = `Characters: ${textarea.value.length}`;
      
      textarea.addEventListener("input", () => {
        counter.innerHTML = `Characters: ${textarea.value.length}`;
      });
      
      el.appendChild(textarea);
      el.appendChild(counter);
    }
    export default { render };
    """
    # Stateful property that can be accessed by JavaScript & Python
    text = traitlets.Unicode("").tag(sync=True)


class SVGDisplayWidget(anywidget.AnyWidget):
    # SVG string to display
    _svg_content = traitlets.Unicode("").tag(sync=True)

    _esm = r"""
function extendElementclickoutside() {
  (function () {
    if (!Element.prototype.__customEventsExtended) {
      // Mark the prototype to prevent multiple executions.
      Element.prototype.__customEventsExtended = true;

      // Retrieve original methods dynamically from the Element's prototype in the prototype chain.
      const originalAddEventListener = Element.prototype.addEventListener;
      const originalRemoveEventListener = Element.prototype.removeEventListener;

      Element.prototype.addEventListener = function (type, listener, options) {
        if (type === "clickOutside") {
          const outsideClickListener = (event) => {
            if (!this.contains(event.target) && this.isConnected) {
              //event.type = "clickOutside";
              listener.call(this, event);
            }
          };

          // Adding the listener to the document to capture all click events
          document.addEventListener("click", outsideClickListener, options);

          // Store in a map to properly remove later
          this._outsideEventListeners =
            this._outsideEventListeners || new Map();
          this._outsideEventListeners.set(listener, outsideClickListener);
        } else {
          // Call the original addEventListener for other types of events
          originalAddEventListener.call(this, type, listener, options);
        }
      };

      Element.prototype.removeEventListener = function (
        type,
        listener,
        options
      ) {
        if (type === "clickOutside") {
          const registeredListener =
            this._outsideEventListeners &&
            this._outsideEventListeners.get(listener);
          if (registeredListener) {
            document.removeEventListener("click", registeredListener, options);
            this._outsideEventListeners.delete(listener);
            if (this._outsideEventListeners.size === 0) {
              delete this._outsideEventListeners;
            }
          }
        } else {
          // Call the original removeEventListener for other types of events
          originalRemoveEventListener.call(this, type, listener, options);
        }
      };
    }
  })();
}
extendElementclickoutside();


/**
 * Manages SVG display state and interactions including path selection,
 * hover effects, and transformations.
 *
 * Handles:
 * - SVG element processing and responsiveness
 * - Path selection state and styling
 * - Original state preservation using data attributes
 * - Mouse hover effects
 * - Keyboard-driven path transformations
 *
 * State transitions:
 * - Initial → Hover (blue)
 * - Hover → Selected (red)
 * - Selected → Original state
 * - Hover → Original state
 */
// SVGDisplayManager.js
class SVGDisplayManager {
  constructor() {
    this.selectedPath = null;
  }

  processSVG(svgElement) {
    const svg = svgElement.querySelector('svg');
    if (!svg) {
      console.warn("No <svg> element found!");
      return;
    }
    console.log("Processing SVG for responsiveness...");
    svg.removeAttribute('width');
    svg.removeAttribute('height');

    if (!svg.hasAttribute('viewBox')) {
      const width = svg.getAttribute('width') || 300;
      const height = svg.getAttribute('height') || 150;
      svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    }

    svg.style.width = '100%';
    svg.style.height = 'auto';
    console.log("SVG processing complete.");
  }

  handleMouseOver(path) {
    if (path !== this.selectedPath) {
      console.log("Path hovered:", path);
      // Only store original values if we haven't already
      if (!path.hasAttribute('data-original-stroke')) {
        path.setAttribute('data-original-stroke', path.getAttribute('stroke') || 'none');
        path.setAttribute('data-original-stroke-width', path.getAttribute('stroke-width') || '1');
      }
      path.setAttribute('stroke', 'blue');
      path.setAttribute('stroke-width', path.getAttribute('data-original-stroke-width') * 2);
    }
  }

  handleMouseOut(path) {
    if (path !== this.selectedPath) {
      // Return to original state
      path.setAttribute('stroke', path.getAttribute('data-original-stroke'));
      path.setAttribute('stroke-width', path.getAttribute('data-original-stroke-width'));
    }
  }

  setSelectedPath(path) {
    // Clear previous selection
    if (this.selectedPath) {
      // Return previous selection to original state
      this.selectedPath.setAttribute('stroke', this.selectedPath.getAttribute('data-original-stroke'));
      this.selectedPath.setAttribute('stroke-width', this.selectedPath.getAttribute('data-original-stroke-width'));
    }

    this.selectedPath = path;

    if (path) {
      // Only store original values if we haven't already
      if (!path.hasAttribute('data-original-stroke')) {
        path.setAttribute('data-original-stroke', path.getAttribute('stroke') || 'none');
        path.setAttribute('data-original-stroke-width', path.getAttribute('stroke-width') || '1');
      }
      path.setAttribute('stroke', 'red');
      path.setAttribute('stroke-width', path.getAttribute('data-original-stroke-width') * 2);
    }
  }

  clearSelection() {
    if (this.selectedPath) {
      console.log("Clearing selection");
      // Return to original state
      this.selectedPath.setAttribute('stroke', this.selectedPath.getAttribute('data-original-stroke'));
      this.selectedPath.setAttribute('stroke-width', this.selectedPath.getAttribute('data-original-stroke-width'));
      this.selectedPath = null;
    }
  }
  
handleKeyDown(event) {
    if (!this.selectedPath) return;

    let translateX = 0;
    let translateY = 0;

    switch (event.key) {
        case 'ArrowUp':
            translateY = -5;
            console.log("Moving selected path up.");
            break;
        case 'ArrowDown':
            translateY = 5;
            console.log("Moving selected path down.");
            break;
        case 'ArrowLeft':
            translateX = -5;
            console.log("Moving selected path left.");
            break;
        case 'ArrowRight':
            translateX = 5;
            console.log("Moving selected path right.");
            break;
        default:
            return;
    }

    let transform = this.selectedPath.getAttribute('transform') || '';
    let transforms = [];
    const transformRegex = /(\w+)\(([^)]*)\)/g;
    let match;
    while ((match = transformRegex.exec(transform)) !== null) {
        transforms.push({
            type: match[1],
            value: match[2]
        });
    }

    if (transforms.length > 0 && transforms[0].type === 'translate') {
        // Update the first translate transform if it exists
        let [existingX, existingY] = transforms[0].value.split(',').map(parseFloat);
        translateX += existingX;
        translateY += existingY;
        transforms[0].value = `${translateX},${translateY}`;
    } else {
        // Prepend a new translate transform if the first one is not translate
        transforms.unshift({ type: 'translate', value: `${translateX},${translateY}` });
    }

    const newTransform = transforms.map(t => `${t.type}(${t.value})`).join(' ');
    this.selectedPath.setAttribute('transform', newTransform);

    event.preventDefault();
    event.stopPropagation();
}

 }

// DOMHelper.js
/**
 * Static helper class for creating standardized DOM elements
 * used in the SVG display.
 * 
 * Provides factory methods for:
 * - SVG container elements with proper tabindex and styling
 * - SVG wrapper elements with consistent dimensions
 */
class DOMHelper {
  static createSvgContainer() {
    const container = document.createElement('div');
    container.setAttribute('tabindex', '0');
    container.style.width = '100%';
    container.style.height = '100%';
    container.style.display = 'flex';
    container.style.justifyContent = 'center';
    container.style.alignItems = 'center';
    container.style.overflow = 'auto';
    return container;
  }

  static createSvgElement() {
    const element = document.createElement('div');
    element.style.width = '100%';
    element.style.height = '100%';
    return element;
  }
}

// EventManager.js
/**
 * Manages event listeners and their lifecycle for SVG interactions.
 * Works in conjunction with SVGDisplayManager to handle user input.
 * 
 * Responsibilities:
 * - Attaches and tracks all event listeners
 * - Handles 'clickOutside' event for deselection
 * - Manages global keyboard events
 * - Ensures proper event cleanup to prevent memory leaks
 * 
 * @param {SVGDisplayManager} svgDisplayManager - The display manager instance to handle visual updates
 */
class EventManager {
  constructor(svgDisplayManager) {
    this.eventListeners = [];
    this.svgDisplayManager = svgDisplayManager;
  }

  attachEventListeners(svgElement, svgContainer, capture = false) {
    const paths = svgElement.querySelectorAll('path');
    if (paths.length === 0) {
      console.warn("No <path> elements found in the SVG!");
      return;
    }

    paths.forEach((path) => {
      const mouseOverHandler = () => this.svgDisplayManager.handleMouseOver(path);
      const mouseOutHandler = () => this.svgDisplayManager.handleMouseOut(path);
      const clickHandler = (e) => {
        svgContainer.focus();
        this.svgDisplayManager.setSelectedPath(path);
      };

      path.addEventListener('mouseover', mouseOverHandler, capture);
      path.addEventListener('mouseout', mouseOutHandler, capture);
      path.addEventListener('click', clickHandler, capture);

      this.eventListeners.push(
        { element: path, event: 'mouseover', handler: mouseOverHandler, capture },
        { element: path, event: 'mouseout', handler: mouseOutHandler, capture },
        { element: path, event: 'click', handler: clickHandler, capture }
      );
    });
    console.log(`Attached event listeners to ${paths.length} <path> elements.`);
  }

  attachGlobalListeners(svgElement, svgContainer) {
    // Handle clickOutside event
    const clickOutsideHandler = () => {
      this.svgDisplayManager.clearSelection();
    };
    svgElement.addEventListener('clickOutside', clickOutsideHandler);
    this.eventListeners.push({ element: svgElement, event: 'clickOutside', handler: clickOutsideHandler });

    // Handle keydown events
    const keydownHandler = (event) => {
      if (event.key === 'Escape') {
        this.svgDisplayManager.clearSelection();
        return;
      }
      this.svgDisplayManager.handleKeyDown(event);
    };

    document.addEventListener('keydown', keydownHandler, true);
    this.eventListeners.push({ element: document, event: 'keydown', handler: keydownHandler, capture: true });
  }

  cleanup() {
    console.log("Cleaning up event listeners...");
    this.eventListeners.forEach(({ element, event, handler, capture }) => {
      element.removeEventListener(event, handler, capture);
    });
    this.eventListeners.length = 0;
  }
}

// render.js
function render({ model, el }) {
  const svgDisplayManager = new SVGDisplayManager();
  const eventManager = new EventManager(svgDisplayManager);
  
  const svgContainer = DOMHelper.createSvgContainer();
  const svgEl = DOMHelper.createSvgElement();

  // Setup change listener on the model
  model.on('change:_svg_content', () => {
    svgEl.innerHTML = model.get('_svg_content');
    svgDisplayManager.processSVG(svgEl);
    eventManager.attachEventListeners(svgEl, svgContainer);
  });

  // Initial render
  svgEl.innerHTML = model.get('_svg_content');
  svgDisplayManager.processSVG(svgEl);
  eventManager.attachEventListeners(svgEl, svgContainer);
  eventManager.attachGlobalListeners(svgEl, svgContainer);

  // DOM setup
  svgContainer.appendChild(svgEl);
  el.appendChild(svgContainer);

  // Setup cleanup observer
  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (Array.from(mutation.removedNodes).includes(el)) {
        cleanup();
        break;
      }
    }
  });

  if (el.parentNode) {
    observer.observe(el.parentNode, { childList: true });
  } else {
    console.warn("Element 'el' is not attached to the DOM. Cleanup observer not set up.");
  }

  // Cleanup function
  function cleanup() {
    console.log("Cleaning up...");
    eventManager.cleanup();
    if (observer) {
      observer.disconnect();
    }
    svgEl.innerHTML = '';
    console.log("Cleanup complete.");
  }

  return cleanup;
}

export default { render };

    """

    def __init__(self, svg_content="", **kwargs):
        """
        Initialize the SVG Display Widget with Path Selection and Movement

        Parameters:
        -----------
        svg_content : str, optional
            The SVG string to display (default is an empty string)
        """
        super().__init__(**kwargs)
        self._svg_content = svg_content


import base64
from ordec.render import render_svg


def ordec_widget(arg):
    svg_content = base64.b64decode(render_svg(arg).as_url().split(",", 1)[1]).decode(
        "utf-8"
    )
    svg_widget = SVGDisplayWidget(svg_content=svg_content)
    return svg_widget


import anywidget
import traitlets
import json
import time
from collections import defaultdict
import numpy as np
import uuid  # Used for triggering updates reliably, I think there is a better way


class AnimatedFnWidget(anywidget.AnyWidget):
    """
    An AnyWidget class for displaying real-time streaming plots using plot-stream-js.

    Maintains a buffer and sends updates to the frontend periodically.
    Provides methods for adding data, updating configuration, setting the view,
    and resetting the plot.
    """

    # Sends the initial configuration ONCE upon widget creation.
    _initial_config_json = traitlets.Unicode("{}").tag(sync=True)

    # Sends batches of new data points {'series': {'x': [...], 'y': [...]}}.
    _new_data_points = traitlets.Unicode("{}").tag(sync=True)

    # Sends commands to update the chart config (axes, legend etc.).
    _update_chart_config_cmd = traitlets.Unicode("{}").tag(sync=True)

    # Sends commands to update specific series configs (color, label etc.).
    _update_series_config_cmd = traitlets.Unicode("{}").tag(sync=True)

    # Sends commands to programmatically set the view (zoom/pan).
    _set_view_cmd = traitlets.Unicode("{}").tag(sync=True)

    # Trigger command to clear all data from the chart.
    _clear_data_cmd = traitlets.Unicode().tag(sync=True)  # Use UUID to ensure change

    # Trigger command to reset the view to show all data.
    _reset_view_cmd = traitlets.Unicode().tag(sync=True)  # Use UUID to ensure change

    _esm = r"""
    import * as d3 from "https://esm.sh/d3@7";

    async function render({ model, el }) {
      console.log("[PlotStream Widget] Initializing...");

      // Using a specific commit hash for stability
      const defineStreamingChart = await import(
          "https://esm.sh/gh/Kreijstal/plot-stream-js@9dec3aa6f73c7a731564e630875f010dbc114a48"
      ).then((mod) => mod.default).catch(err => {
          console.error("Failed to load plot-stream-js:", err);
          el.textContent = `Error loading charting library: ${err.message}. Check console.`;
          return null; // Indicate failure
      });

      if (!defineStreamingChart) return; // Stop if library failed to load

      
      const lib = defineStreamingChart(d3);
      if (!lib || !lib.StreamingChart) {
           console.error("Failed to get StreamingChart class after injecting D3.");
           el.textContent = "Error initializing charting library (StreamingChart class not found).";
           return; // Stop if class definition failed
      }
      const { StreamingChart } = lib;

      // 3. Prepare Container (use the element provided by anywidget)
      el.style.width = '100%';
      el.style.height = '400px'; 
      el.style.border = '1px solid #ccc'; 
      el.style.position = 'relative';  

      function translateConfig(pyConfig) {
          const chartConfig = {
              xAxis: {
                  label: pyConfig.xLabel || "t", // Default label 't'
                  range: { min: pyConfig.xMin ?? null, max: pyConfig.xMax ?? null },
                  showGridLines: pyConfig.xGrid ?? true, // Default true
              },
              yAxis: {
                  label: pyConfig.yLabel || "", // Default empty label
                  // Use null for auto-scaling if pyConfig.yMin/yMax are explicitly None/null
                  range: { min: pyConfig.yMin, max: pyConfig.yMax }, // Pass null/undefined directly
                  showGridLines: pyConfig.yGrid ?? true, // Default true
              },
              series: pyConfig.series || {}, // Pass series config directly (format matches)
              legend: {
                  visible: pyConfig.legendVisible ?? true, // Default true
                  position: pyConfig.legendPosition || 'top-right', // Default top-right
              },
              interactions: { // Enable interactions by default
                  zoom: pyConfig.enableZoom ?? true,
                  pan: pyConfig.enablePan ?? true,
                  tooltip: pyConfig.enableTooltip ?? false, // Tooltip might not be implemented yet
              },
              maxDataPointsPerSeries: pyConfig.maxDataPointsPerSeries ?? 50000 // Sensible default
          };

          // Clean up undefined ranges if both min/max are undefined/null
          if (chartConfig.xAxis.range.min === null && chartConfig.xAxis.range.max === null) {
              delete chartConfig.xAxis.range; // Let library use defaults
          }
          if (chartConfig.yAxis.range.min === null && chartConfig.yAxis.range.max === null) {
              delete chartConfig.yAxis.range; // Let library use defaults (auto-scale)
          } else {
             // Ensure null is passed if only one bound is specified but the other is undefined
             chartConfig.yAxis.range.min = chartConfig.yAxis.range.min ?? null;
             chartConfig.yAxis.range.max = chartConfig.yAxis.range.max ?? null;
          }


          console.log("[PlotStream Widget] Translated Initial Config:", chartConfig);
          return chartConfig;
      }

      let chart;
      try {
          const initialPyConfig = JSON.parse(model.get('_initial_config_json'));
          const initialChartConfig = translateConfig(initialPyConfig);
          chart = new StreamingChart(el, initialChartConfig);
          console.log("[PlotStream Widget] StreamingChart initialized.");
      } catch (error) {
          console.error("[PlotStream Widget] Failed to initialize StreamingChart:", error);
          el.textContent = `Error creating chart: ${error.message}`;
          return; // Stop if initialization fails
      }
   
      
      model.on('change:_new_data_points', () => {
          const newDataJson = model.get('_new_data_points');
          if (!newDataJson || newDataJson === '{}') return; // Ignore empty updates
          try {
              const newData = JSON.parse(newDataJson);
              if (chart && Object.keys(newData).length > 0) {
                  chart.addData(newData);
              }
          } catch (e) {
              console.error("[PlotStream Widget] Error parsing/adding new data points:", e, newDataJson);
          }
      });
 
      model.on('change:_update_chart_config_cmd', () => {
          const configUpdateJson = model.get('_update_chart_config_cmd');
          if (!configUpdateJson || configUpdateJson === '{}') return;
           try {
                const pyConfigUpdate = JSON.parse(configUpdateJson);
                // Translate only the parts relevant to updateChartConfig
                const chartConfigUpdate = {};
                if (pyConfigUpdate.hasOwnProperty('xMin') || pyConfigUpdate.hasOwnProperty('xMax') || pyConfigUpdate.hasOwnProperty('xLabel') || pyConfigUpdate.hasOwnProperty('xGrid')) {
                   chartConfigUpdate.xAxis = {
                       label: pyConfigUpdate.xLabel, // undefined is fine
                       range: { min: pyConfigUpdate.xMin ?? null, max: pyConfigUpdate.xMax ?? null },
                       showGridLines: pyConfigUpdate.xGrid
                   };
                   // Clean up range object if min/max are not provided
                   if (chartConfigUpdate.xAxis.range.min === null && chartConfigUpdate.xAxis.range.max === null) delete chartConfigUpdate.xAxis.range;
                   if (chartConfigUpdate.xAxis.label === undefined) delete chartConfigUpdate.xAxis.label;
                   if (chartConfigUpdate.xAxis.showGridLines === undefined) delete chartConfigUpdate.xAxis.showGridLines;
                }
                 if (pyConfigUpdate.hasOwnProperty('yMin') || pyConfigUpdate.hasOwnProperty('yMax') || pyConfigUpdate.hasOwnProperty('yLabel') || pyConfigUpdate.hasOwnProperty('yGrid')) {
                   chartConfigUpdate.yAxis = {
                       label: pyConfigUpdate.yLabel,
                       range: { min: pyConfigUpdate.yMin, max: pyConfigUpdate.yMax }, // Pass null/undefined
                       showGridLines: pyConfigUpdate.yGrid
                   };
                   if (chartConfigUpdate.yAxis.range.min === undefined && chartConfigUpdate.yAxis.range.max === undefined) delete chartConfigUpdate.yAxis.range;
                   else { // Ensure null is passed explicitly if needed
                      chartConfigUpdate.yAxis.range.min = chartConfigUpdate.yAxis.range.min ?? null;
                      chartConfigUpdate.yAxis.range.max = chartConfigUpdate.yAxis.range.max ?? null;
                   }
                   if (chartConfigUpdate.yAxis.label === undefined) delete chartConfigUpdate.yAxis.label;
                   if (chartConfigUpdate.yAxis.showGridLines === undefined) delete chartConfigUpdate.yAxis.showGridLines;
                }
                 if (pyConfigUpdate.hasOwnProperty('legendVisible') || pyConfigUpdate.hasOwnProperty('legendPosition')) {
                   chartConfigUpdate.legend = {
                       visible: pyConfigUpdate.legendVisible,
                       position: pyConfigUpdate.legendPosition
                   };
                   if (chartConfigUpdate.legend.visible === undefined) delete chartConfigUpdate.legend.visible;
                   if (chartConfigUpdate.legend.position === undefined) delete chartConfigUpdate.legend.position;
                }
                 if (pyConfigUpdate.hasOwnProperty('maxDataPointsPerSeries')) {
                    chartConfigUpdate.maxDataPointsPerSeries = pyConfigUpdate.maxDataPointsPerSeries;
                 }
                 // Add interactions update if needed
                 if (pyConfigUpdate.hasOwnProperty('enableZoom') || pyConfigUpdate.hasOwnProperty('enablePan') || pyConfigUpdate.hasOwnProperty('enableTooltip')) {
                    chartConfigUpdate.interactions = {
                       zoom: pyConfigUpdate.enableZoom,
                       pan: pyConfigUpdate.enablePan,
                       tooltip: pyConfigUpdate.enableTooltip
                    };
                    // remove undefined interaction keys
                    Object.keys(chartConfigUpdate.interactions).forEach(key => chartConfigUpdate.interactions[key] === undefined && delete chartConfigUpdate.interactions[key]);
                 }


                if (chart && Object.keys(chartConfigUpdate).length > 0) {
                    console.log("[PlotStream Widget] Applying Chart Config Update:", chartConfigUpdate);
                    chart.updateChartConfig(chartConfigUpdate);
                }
           } catch(e) {
                console.error("[PlotStream Widget] Error parsing/applying chart config update:", e, configUpdateJson);
           }
      });
    
       model.on('change:_update_series_config_cmd', () => {
            const seriesUpdateJson = model.get('_update_series_config_cmd');
            if (!seriesUpdateJson || seriesUpdateJson === '{}') return;
            try {
                const seriesUpdates = JSON.parse(seriesUpdateJson); // Expects { "seriesId": { ...config... }, ... }
                if (chart) {
                    Object.entries(seriesUpdates).forEach(([seriesId, config]) => {
                         console.log(`[PlotStream Widget] Updating series "${seriesId}" config:`, config);
                         chart.updateSeriesConfig(seriesId, config);
                    });
                }
            } catch(e) {
                console.error("[PlotStream Widget] Error parsing/applying series config update:", e, seriesUpdateJson);
            }
       });

      
      model.on('change:_set_view_cmd', () => {
          const viewCmdJson = model.get('_set_view_cmd');
           if (!viewCmdJson || viewCmdJson === '{}') return;
          try {
              const viewOptions = JSON.parse(viewCmdJson); // { xMin?, xMax?, yMin?, yMax? }
              if (chart && Object.keys(viewOptions).length > 0) {
                  console.log("[PlotStream Widget] Setting view:", viewOptions);
                  // Add transition option if desired, e.g., { transition: 200 }
                  chart.setView(viewOptions);
              }
          } catch (e) {
              console.error("[PlotStream Widget] Error parsing/setting view:", e, viewCmdJson);
          }
      });

      
      model.on('change:_clear_data_cmd', () => {
          // The value doesn't matter, only the change event
          if (chart) {
              console.log("[PlotStream Widget] Clearing data.");
              chart.clearData();
          }
      });

       
       model.on('change:_reset_view_cmd', () => {
           // The value doesn't matter, only the change event
           if (chart) {
               console.log("[PlotStream Widget] Resetting view.");
               // Add transition option if desired, e.g., { transition: 200 }
               chart.resetView();
           }
       });


      
      return () => {
          console.log("[PlotStream Widget] Cleaning up chart instance.");
          if (chart) {
              chart.destroy();
          }
          // No need to remove resize listeners etc., chart.destroy() handles it.
           el.innerHTML = ""; // Clear the container
      };
    }

    export default { render };
    """

    def __init__(self, update_interval_ms=100, config=None, **kwargs):
        """
        Initializes the AnimatedFnWidget.

        Args:
            update_interval_ms (int): Interval in milliseconds for buffering data
                                      before sending to the frontend.
            config (dict, optional): Initial configuration for the plot.
                                     Keys match plot-stream-js options closely,
                                     but with camelCase often mapped from snake_case
                                     or direct mapping. Examples:
                                     `xMin`, `xMax`, `yMin`, `yMax`, `xLabel`, `yLabel`,
                                     `xGrid`, `yGrid`, `legendVisible`, `legendPosition`,
                                     `maxDataPointsPerSeries`, `enableZoom`, `enablePan`,
                                     `series` (dict mapping seriesId to its config like
                                     `{'label': 'Sine', 'color': '#ff0000'}`).
            **kwargs: Additional arguments passed to anywidget.AnyWidget.
        """
        super().__init__(**kwargs)

        # Default configuration values
        default_config = {
            "xMin": None,
            "xMax": None,  # Default X range
            "yMin": None,
            "yMax": None,  # Default to auto-Y
            "xLabel": "t",
            "yLabel": "",
            "xGrid": True,
            "yGrid": True,
            "legendVisible": True,
            "legendPosition": "top-right",
            "series": {},  # Empty series definitions initially
            "maxDataPointsPerSeries": 500000,
            "enableZoom": True,
            "enablePan": True,
            "enableTooltip": False,  # Assuming tooltip isn't ready/needed yet
        }

        # Merge user-provided config with defaults
        initial_config = config if config is not None else {}
        merged_config = {**default_config, **initial_config}

        # Store the merged config and send it to JS via the initial traitlet
        self._internal_config = merged_config  # Keep track internally
        self._initial_config_json = json.dumps(merged_config)

        # Buffering setup
        self.update_interval = update_interval_ms / 1000.0
        self.last_update_time = 0
        self.buffer = defaultdict(lambda: {"x": [], "y": []})

        print(
            f"[PlotStream Widget] Python initialized. Update interval: {update_interval_ms}ms"
        )

    def _flush_buffer(self):
        """Sends buffered data to JavaScript and clears the buffer."""
        if not self.buffer:
            return

        data_to_send = {}
        for series, points in self.buffer.items():
            if points["x"]:  # Only include series with new data
                # Send copies of the lists
                data_to_send[series] = {"x": points["x"][:], "y": points["y"][:]}

        if data_to_send:
            try:
                # print(f"[PlotStream Widget] Flushing buffer: {json.dumps(data_to_send)}") # Debug
                self._new_data_points = json.dumps(data_to_send)
                # Clear buffer *after* successful send attempt
                for series in list(data_to_send.keys()):  # Use keys from data_to_send
                    if (
                        series in self.buffer
                    ):  # Check if still exists (might not be needed)
                        self.buffer[series]["x"].clear()
                        self.buffer[series]["y"].clear()
                self.last_update_time = time.time()
            except Exception as e:
                print(f"[PlotStream Widget] Error sending data points: {e}")

    def add_points(self, series_name, x_values, y_values):
        """
        Adds data points to a specific series and buffers them for sending.

        Args:
            series_name (str): The name/identifier of the data series.
            x_values (list | np.ndarray): A list or NumPy array of X values.
            y_values (list | np.ndarray): A list or NumPy array of Y values.
                                          Must be the same length as x_values.
                                          Can contain `None` for gaps.
        """
        if not isinstance(series_name, str) or not series_name:
            raise ValueError("series_name must be a non-empty string")

        # Ensure x and y are lists and handle numpy arrays
        x_list = (
            x_values.tolist() if isinstance(x_values, np.ndarray) else list(x_values)
        )
        y_list = (
            y_values.tolist() if isinstance(y_values, np.ndarray) else list(y_values)
        )

        if len(x_list) != len(y_list):
            raise ValueError(
                f"x_values (len {len(x_list)}) and y_values (len {len(y_list)}) must have the same length for series '{series_name}'"
            )
        if len(x_list) == 0:
            return  # Nothing to add

        # Append data to the buffer for the given series
        self.buffer[series_name]["x"].extend(x_list)
        self.buffer[series_name]["y"].extend(y_list)

        # Check if it's time to flush the buffer
        current_time = time.time()
        if current_time - self.last_update_time >= self.update_interval:
            self._flush_buffer()

    def update_config(self, config_dict):
        """
        Updates the chart's configuration after initialization.

        Merges the provided dictionary with the current configuration.
        Sends separate commands for chart-level and series-level updates.

        Args:
            config_dict (dict): A dictionary containing configuration keys to update.
                                Uses the same keys as the `config` parameter in `__init__`.
        """
        if not isinstance(config_dict, dict):
            print("Warning: update_config expects a dictionary.")
            return

        print(f"[PlotStream Widget] Updating config with: {config_dict}")

        chart_config_updates = {}
        series_config_updates = {}

        # Separate series updates from general chart updates
        for key, value in config_dict.items():
            if key == "series":
                if isinstance(value, dict):
                    # Update internal config for series part
                    self._internal_config.setdefault("series", {}).update(value)
                    # Add to series-specific command payload
                    series_config_updates.update(value)
                else:
                    print(
                        f"Warning: 'series' key in update_config should be a dict, got {type(value)}. Ignoring."
                    )
            else:
                # Update internal config for chart-level part
                self._internal_config[key] = value
                # Add to chart-level command payload
                chart_config_updates[key] = value

        # Validate updated config parts before sending
        check_xMin = self._internal_config.get("xMin")
        check_xMax = self._internal_config.get("xMax")
        check_yMin = self._internal_config.get("yMin")
        check_yMax = self._internal_config.get("yMax")

        if (
            check_xMin is not None
            and check_xMax is not None
            and check_xMax <= check_xMin
        ):
            print(
                f"Warning: Invalid x-axis range after update (xMin={check_xMin}, xMax={check_xMax}). Check config."
            )
            # return # Option: prevent sending

        if (
            check_yMin is not None
            and check_yMax is not None
            and check_yMax <= check_yMin
        ):
            print(
                f"Warning: Invalid y-axis range after update (yMin={check_yMin}, yMax={check_yMax}). Check config."
            )
            # return # Option: prevent sending

        # Send update commands to JavaScript
        if chart_config_updates:
            try:
                self._update_chart_config_cmd = json.dumps(chart_config_updates)
            except Exception as e:
                print(f"Error sending chart config update: {e}")

        if series_config_updates:
            try:
                self._update_series_config_cmd = json.dumps(series_config_updates)
            except Exception as e:
                print(f"Error sending series config update: {e}")

    def set_view(self, x_min=None, x_max=None, y_min="keep", y_max="keep"):
        """
        Sets the visible range (view) of the plot programmatically.

        Args:
            x_min (float, optional): Minimum X value for the view. Defaults to None (no change).
            x_max (float, optional): Maximum X value for the view. Defaults to None (no change).
            y_min (float | None | str): Minimum Y value. Use `None` to enable auto-scaling for Y min.
                                         Defaults to "keep" (no change).
            y_max (float | None | str): Maximum Y value. Use `None` to enable auto-scaling for Y max.
                                         Defaults to "keep" (no change).
        """
        view_options = {}
        if x_min is not None:
            view_options["xMin"] = x_min
        if x_max is not None:
            view_options["xMax"] = x_max
        if y_min != "keep":
            view_options["yMin"] = y_min  # Pass None directly
        if y_max != "keep":
            view_options["yMax"] = y_max  # Pass None directly

        if not view_options:
            print("Info: set_view called with no changes specified.")
            return  # Nothing to do

        # Basic validation for ranges before sending command
        check_xMin = view_options.get("xMin", self._internal_config.get("xMin"))
        check_xMax = view_options.get("xMax", self._internal_config.get("xMax"))
        check_yMin = view_options.get("yMin", self._internal_config.get("yMin"))
        check_yMax = view_options.get("yMax", self._internal_config.get("yMax"))

        # Check if yMin/yMax are None (auto-scale request) or numeric
        y_range_valid = True
        if isinstance(check_yMin, (int, float)) and isinstance(
            check_yMax, (int, float)
        ):
            if check_yMax <= check_yMin:
                y_range_valid = False
                print(
                    f"Warning: Invalid y-axis range provided to set_view (yMin={check_yMin}, yMax={check_yMax}). Ignoring y range change."
                )
                view_options.pop("yMin", None)
                view_options.pop("yMax", None)
        elif check_yMin == "keep" or check_yMax == "keep":
            pass  # Ignore validation if keeping old values
        elif check_yMin is not None and not isinstance(check_yMin, (int, float)):
            print(
                f"Warning: Invalid y_min type '{type(check_yMin)}' in set_view. Use number or None."
            )
            view_options.pop("yMin", None)
            y_range_valid = False
        elif check_yMax is not None and not isinstance(check_yMax, (int, float)):
            print(
                f"Warning: Invalid y_max type '{type(check_yMax)}' in set_view. Use number or None."
            )
            view_options.pop("yMax", None)
            y_range_valid = False

        # Validate X range
        if isinstance(check_xMin, (int, float)) and isinstance(
            check_xMax, (int, float)
        ):
            if check_xMax <= check_xMin:
                print(
                    f"Warning: Invalid x-axis range provided to set_view (xMin={check_xMin}, xMax={check_xMax}). Ignoring x range change."
                )
                view_options.pop("xMin", None)
                view_options.pop("xMax", None)

        if not view_options:
            print("Info: set_view call resulted in no valid changes after validation.")
            return

        # Send command if there are valid options left
        try:
            self._set_view_cmd = json.dumps(view_options)
        except Exception as e:
            print(f"Error sending set view command: {e}")

    def reset_data(self):
        """Clears all plotted data from the chart on the frontend."""
        print("[PlotStream Widget] Requesting data clear.")
        self.buffer.clear()  # Clear Python buffer immediately
        self.last_update_time = 0
        try:
            # Trigger JS by changing the traitlet value using a unique ID
            self._clear_data_cmd = str(uuid.uuid4())
        except Exception as e:
            print(f"Error sending clear data command: {e}")

    def reset_view(self):
        """Resets the chart view to show the full extent of the current data."""
        print("[PlotStream Widget] Requesting view reset.")
        try:
            # Trigger JS by changing the traitlet value using a unique ID
            self._reset_view_cmd = str(uuid.uuid4())
        except Exception as e:
            print(f"Error sending reset view command: {e}")

    def finalize(self):
        """Flushes any remaining data in the buffer."""
        print("[PlotStream Widget] Finalizing: Flushing remaining buffer...")
        self._flush_buffer()
        print("[PlotStream Widget] Finalizing complete.")
