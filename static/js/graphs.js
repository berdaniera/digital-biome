var margin = {top: 40, right: 40, bottom: 40, left: 40},
    width = $("#graphs").width() - margin.left - margin.right,
    height = 250 - margin.top - margin.bottom;
var parseDate = d3.utcParse("%Y-%m-%dT%H:%M:%SZ");
var parseDateFull = d3.utcParse("%Y-%m-%dT%H:%M:%S.%LZ");
var x = d3.scaleUtc().range([0, width]),
    y = d3.scaleLinear().range([height, 0]),
    xAxis = d3.axisBottom().scale(x).ticks(6);
var brush = d3.brushX()
  .on("start", brushstart)
  .on("brush", brushmove);
  // .on("end", brushend);
var selectedBrush;
var data;
var variables;
var sundat;
var flags;
var datna;
var zoom_in;
var brushdown = true; //variable for if brushing all panels

function Plots(variables, data, flags, page){
  data.forEach(function(d){ d.date = parseDate(d['datetime']) });
  x.domain(d3.extent(data, function(d) { return d.date; }));
  for (var i = 0; i < variables.length; ++i) {
    vvv = variables[i];
    if(datna != null){ // check if NA, need to rescale Y axis
      y.domain(d3.extent(datna, function(d) { return d[vvv]; }));
    }else{
      y.domain(d3.extent(data, function(d) { return d[vvv]; }));
    }
    var line = d3.line()
        .defined(function(d){ return d[vvv];})
        .x(function(d){ return x(d.date); })
        .y(function(d){ return y(d[vvv]); });
    var svg = d3.select("#graphs").append("svg")
      .datum(data)
        .attr("class",vvv)
        .attr("width", width + margin.left + margin.right)
        .attr("height", height + margin.top + margin.bottom)
      .append("g")
        .attr("transform", "translate(" + margin.left + "," + margin.top + ")");
    svg.append("g")
        .attr("class", "axis axis--x")
        .attr("transform", "translate(0," + height + ")")
        .call(xAxis)
        .append("text")
          .attr("fill", "#000")
          .attr("dy", "3em")
          .attr("dx", width)
          .style("text-anchor", "end")
          .text("datetime (UTC)");
    svg.append("g")
        .attr("class", "axis axis--y")
        .call(d3.axisLeft().scale(y).ticks(3))
      .append("text")
        .attr("fill", "#000")
        .attr("dy", "-0.71em")
        .attr("dx", "0.71em")
        .style("text-anchor", "start")
        .text(vvv);
    svg.append("g")
        .attr("class", "backgraph");
    svg.append("g")
        .attr("class", "sunriseset");
    svg.selectAll(".dot")
        .data(data.filter(function(d) { return d[vvv]; }))
      .enter().append("circle")
        .attr("class", "dot")
        .attr("cx", line.x())
        .attr("cy", line.y())
        .attr("r", 2)
      .classed("flagdot", function(d){
        return flags.includes(d.datetime)
      });
    // code for qaqc page
    if(page=="qaqc"){
      svg.on('dblclick',function(){ redrawPoints(zoom_in=true, sbrush=selectedBrush, reset=true) });
      svg.append("g").attr("class","brush")
        .attr("id", vvv)
        .call(brush);
    }
  }
}

function Sunlight(variables, sundat){
  d3.selectAll(".sunriseset").remove();
  extent = x.domain();
  for (var i = 0; i < variables.length; ++i) {
    vvv = variables[i];
    d3.select("."+vvv).selectAll('.sunriseset')
        .data(sundat)
      .enter().append('rect')
        .attr('class', 'sunriseset')
        .attr('x', function(d) { return x(d.set); })
        .attr('y', 0)
        .attr('width', function(d) { return x(d.rise) - x(d.set); })
        .attr('height', height)
        .attr("transform", "translate(" + margin.left + "," + margin.top + ")")
      .classed("outside", function(d) {
        is_inplot = extent[0] > d.rise || d.set > extent[1];
        return is_inplot;
      });

  }
}
$(function(){
  $('#shownight').change(function() {
    if($(this).is(":checked")) {
      Sunlight(variables, sundat);
    }else{
      d3.select("#graphs").selectAll(".sunriseset").remove();
    }
  });
})

function BackGraph(vvv, graph, data){
  var ynew = d3.scaleLinear().range([height, 0]);
  svg = d3.select("."+graph).select(".backgraph")
  svg.select("path").remove() // remove previous graph
  // ynew.domain(d3.extent(data, function(d) { return d[vvv]; }));
  if(datna != null){
    ynew.domain(d3.extent(datna, function(d) { return d[vvv]; }));
  }else{
    ynew.domain(d3.extent(data, function(d) { return d[vvv]; }));
  }
  var area = d3.area()
      .defined(function(d){
        if(d[vvv]==null || d.date < x.domain()[0] || d.date > x.domain()[1]){
          rrr = false
        }else{
          rrr = true
        }
        return rrr
      })
      .x(function(d) { return x(d.date); })
      .y0(height).y1(function(d) { return ynew(d[vvv]); });
  svg.append("path")
      .datum(data)
      .attr("class", "backarea")
      .attr("d", area);
}
$(function(){
  $("#backgraphlist").change(function () {
    var backfill = this.value;
    for (var i = 0; i < variables.length; ++i) {
      BackGraph(backfill, variables[i], data);
    }
  });
})

// Clear the previously-active brush, if any.
function brushstart() {
  d3.select("."+selectedBrush).select(".brush").call(brush.move, null);
  d3.selectAll(".dot").classed("selected", false); // clear on new start
  // d3.selectAll(".brush").clear();
  // d3.selectAll(".brush").call(brush.move, null);
  selectedBrush = $(this).attr("id")
}
function brushmove() {
  var s = d3.event.selection;
  if (s) {
    ext0 = x.invert(s[0]);
    ext1 = x.invert(s[1]);
    if(brushdown){ // select all dots
      var dott = d3.selectAll(".dot")
    }else{ // select just these dots
      var dott = d3.select("."+selectedBrush).selectAll(".dot")
    }
    dott.classed("selected", function(d) {
      is_brushed = ext0 <= d.date && d.date <= ext1;
      return is_brushed;
    });
  }
}
// function brushend(){}

function redrawPoints(zoom_in, sbrush, reset){
  sbb = d3.select("."+sbrush).select(".brush").node()
  if(!sbb){ // check if there is a brush
    s = null
  }else{ // if it exists, get the extent
    s = d3.brushSelection(sbb)
  }
  if(!s || reset){ // nothing selected or resetting graph, extent goes to maximum
    extent = d3.extent(data, function(d) { return d.date; })//"none"
  }else{ // calculate extent bounds
    ext0 = x.invert(s[0])
    ext1 = x.invert(s[1])
    extent = [ext0,ext1]
  }
  if(zoom_in){ // if zooming, reset the extent
    x.domain(extent);
  }

  // redraw data
  for (var i = 0; i < variables.length; ++i) {
    vvv = variables[i];
    if(datna != null){ // draw with the NA data...
      dna = {}
      datna.forEach(function(e){dna[e.datetime]=e[vvv]})
      y.domain(d3.extent(datna, function(d) { return d[vvv]; })); // reset Y to get rid of NA values
    }else{
      dna = {}
      data.forEach(function(e){dna[e.datetime]=e[vvv]})
      y.domain(d3.extent(data, function(d) { return d[vvv]; })); // reset Y to get rid of NA values
    }
    d3.select("."+vvv).select(".axis--x").call(xAxis); //redraw axis
    var line = d3.line()
        .defined(function(d){return d[vvv];})
        .x(function(d) { return x(d.date); })
        .y(function(d) { return y(d[vvv]); });
    d3.select("."+vvv).selectAll(".dot")
        .attr("cx", line.x())
        .attr("cy", line.y())
    d3.select("."+vvv).selectAll('.sunriseset')
        .attr('x', function(d) { return x(d.set); })
        .attr('width', function(d) { return x(d.rise) - x(d.set); })
    // if(!zoom_in){ // adding na values
    d3.select("."+vvv).selectAll(".dot")
      .classed("outside", function(d) {
        return dna[d.datetime] == null;
      });
    // }
    if(zoom_in){ // check for outside points
      // redraw points
      d3.select("."+vvv).selectAll(".dot")
        .classed("outside", function(d) {
          is_inplot = extent[0] > d.date || d.date > extent[1];
          return is_inplot;
        });
      // redraw sunriseset
      d3.selectAll(".sunriseset")
        .classed("outside", function(d) {
          is_inplot = extent[0] > d.rise || d.set > extent[1];
          return is_inplot;
        });
      // redraw backfill
      var backfill = $("#backgraphlist").val();
      BackGraph(backfill, vvv, data);
    }
  }
  d3.selectAll(".dot").classed("selected", false);
  d3.selectAll(".brush").call(brush.move, null);
  var selectedBrush;
}
