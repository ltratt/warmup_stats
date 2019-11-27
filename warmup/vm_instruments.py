"""Parsers to deal with the data from instrumented VMs.
"""
import abc


def merge_instr_data(file_data):
    """Merge data from one or more instr_data JSON dictionaries.
    """
    instr_data = {'raw_vm_events': list()}
    for dict_ in file_data:
        instr_data['raw_vm_events'].append(dict_['raw_vm_events'])
    return instr_data


class ChartData(object):
    """Class to hold data needed by the plotting script.
    Each VM parser may parse a number of different events which need to be
    plotted (e.g. compilation events, GC, etc.). These should be stored in
    a list of ChartData objects, so that the plotting script does not have to
    know anything about the individual VMs.
    """

    def __init__(self, title, data, legend_text):
        self.title = title
        self.data = data
        self.legend_text = legend_text


class VMInstrumentParser(object):
    """Base class for VM instrumentation parsers.
    We expect one subclass per VM.
    """

    def __init__(self, vm):
        self.vm = vm
        self.chart_data = None

    @abc.abstractmethod
    def parse_instr_data(self):
        """Parse VM instrumentation data.
        """
        return

class HotSpotInstrumentParser(VMInstrumentParser):
    """Parser for Oracle Hotspot instrumentation data.
    Data is in JSON format, and of the form:
      [iterNum, cumuCompTime, collectorInfo]

    Where collectorInfo is a list of the form:
      [collectorName, PoolNames, cumuCollectTime, cumuCollectCount]

    'cumu' means 'cumulative' and times are in milliseconds. collectorNames may
    'not be unique.

    Example line:
     [0, 17, [['PS Scavenge', ['PS Eden Space', 'PS Survivor Space'], 0, 0]]]
    """

    def __init__(self, instr_data):
        VMInstrumentParser.__init__(self, 'Hotspot')
        self.instr_data = instr_data if instr_data else None
        self.parse_instr_data()

    def parse_instr_data(self):
        if self.instr_data is None:
            return None
        raw_events = self.instr_data['raw_vm_events']
        iterations = len(raw_events)
        jit_cumulative_times = [raw_events[i][1] for i in xrange(iterations)]
        gc_cumulative_times = list()
        # Sum GC times over all collectors that ran in each iteration.
        for iteration in xrange(iterations):
            gc_iteration = 0
            for collector in raw_events[iteration][2]:
                gc_iteration += collector[-1]
            gc_cumulative_times.append(gc_iteration)
        # Turn the cumulative times in milliseconds into non-cumulative
        # times in seconds.
        jit_times_secs = [jit_cumulative_times[0] / 1000.0]
        gc_times_secs = [gc_cumulative_times[0] / 1000.0]
        last_jit_time = jit_cumulative_times[0]
        last_gc_time = gc_cumulative_times[0]
        for iteration in xrange(1, iterations):
            jit_times_secs.append((jit_cumulative_times[iteration] - last_jit_time) / 1000.0)
            last_jit_time = jit_cumulative_times[iteration]
            gc_times_secs.append((gc_cumulative_times[iteration] - last_gc_time) / 1000.0)
            last_gc_time = gc_cumulative_times[iteration]
        assert len(jit_times_secs) == len(jit_cumulative_times)
        assert len(gc_times_secs) == len(gc_cumulative_times)
        self.chart_data = [
            ChartData('GC (secs)', gc_times_secs, 'GC events'),
            ChartData('JIT (secs)', jit_times_secs, 'JIT compilation')]


class PyPyInstrumentParser(VMInstrumentParser):
    """Parser for PyPy instrumentation data."""

    def __init__(self, instr_data):
        VMInstrumentParser.__init__(self, 'PyPy')
        self.instr_data = instr_data if instr_data else None
        self.parse_instr_data()

    def parse_instr_data(self):
        if self.instr_data is None:
            return None
        iterations = {'gc': [], 'jit': None}
        for node in self.instr_data['raw_vm_events']:
            event_type, start_time, stop_time, children = node
            assert start_time == stop_time == None
            iteration = {'gc': 0}
            for child in children:
                self._parse_node(child, iteration)
            iterations['gc'].append(iteration['gc'])
        iterations['jit'] = self.instr_data['jit_times']
        self.chart_data = (
            [ChartData('GC', iterations['gc'], 'GC events') ,
             ChartData('JIT', iterations['jit'], 'JIT tracing')])

    def _parse_node(self, node, info):
        """Recurse the event tree summing time spent in gc and tracing.
        """
        event_type, start_time, stop_time, children = node
        assert event_type != 'root'
        child_time = 0
        for child in children:
            child_time += self._parse_node(child, info)
        gross_time = stop_time - start_time
        net_time = gross_time - child_time
        if event_type.startswith('gc-'):
            info['gc'] += net_time
        elif event_type.startswith('jit-'):
            info['jit'] += net_time
        else:
            print 'WARNING: unknown event in PyPy instrumentation: %s' % event_type
        return net_time


# Mapping from VM name -> parser class.
# This enables the main scripts to parse instrumentation data based only
# on the vm:bench:language triplets found in Krun data files.
INSTRUMENTATION_PARSERS = { 'HotSpot': HotSpotInstrumentParser,
                            'PyPy': PyPyInstrumentParser, }
