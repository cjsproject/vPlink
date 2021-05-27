# -*- coding: utf-8 -*-
#
#   Copyright (C) 2007-present Marc Culler, Nathan Dunfield and others.
#
#   This program is distributed under the terms of the
#   GNU General Public License, version 2 or later, as published by
#   the Free Software Foundation.  See the file gpl-2.0.txt for details.
#   The URL for this program is
#     http://www.math.uic.edu/~t3m/plink
#   A copy of the license file may be found at:
#     http://www.gnu.org/licenses/old-licenses/gpl-2.0.html
#
#   The development of this program was partially supported by
#   the National Science Foundation under grants DMS0608567,
#   DMS0504975 and DMS0204142.
"""
This module exports the LinkManager class.  A LinkManager encapsulates
a PL link diagram and provides many methods for importing and exporting
diagrams as well as computing features of the diagram, such as the components
of the link.
"""

import time
from string import ascii_lowercase
from gui import tkMessageBox
from vertex import Vertex
from arrow import Arrow, default_arrow_params
from crossings import Crossing, ECrossing
from smooth import TikZPicture

DT_alphabet = '_abcdefghijklmnopqrstuvwxyzZYXWVUTSRQPONMLKJIHGFEDCBA'


class LinkManager:
    """
    Manages the data associated with a link projection.
    """

    def __init__(self):
        self.initialize()

    def initialize(self, canvas=None):
        self.Arrows = []
        self.Vertices = []
        self.Crossings = []
        self.CrossPoints = []
        self.LiveArrow1 = None
        self.LiveArrow2 = None
        self.ActiveVertex = None
        self.DTlabels = []
        self.labels = []
        self.shift_stamp = time.time()
        self.shift_delta = (0, 0)
        self.shifting = False
        self.canvas = canvas
        self.arrow_params = default_arrow_params.copy()

    def _from_string(self, contents):
        lines = [line for line in contents.split('\n') if len(line) > 0]
        num_lines = len(lines)
        first_line = lines.pop(0)
        has_virtual_crossings = first_line.startswith('% Virtual Link Projection')
        if not (first_line.startswith('% Link Projection') or first_line.startswith('% Virtual Link Projection')):
            tkMessageBox.showwarning(
                'Bad file',
                'This is not a SnapPea link projection file')
        else:
            try:
                vertices, arrows, crossings = [], [], []
                num_components = int(lines.pop(0))
                for n in range(num_components):
                    lines.pop(0)  # We don't need this
                num_vertices = int(lines.pop(0))
                for n in range(num_vertices):
                    x, y = lines.pop(0).split()
                    vertices.append((x, y))
                num_arrows = int(lines.pop(0))
                for n in range(num_arrows):
                    s, e = lines.pop(0).split()
                    arrows.append((s, e))
                num_crossings = int(lines.pop(0))
                for n in range(num_crossings):
                    if has_virtual_crossings:
                        v, u, o = lines.pop(0).split()
                        v, u, o = v == 'v', int(u), int(o)
                        crossings.append((u, o, v, None))
                    else:
                        u, o = lines.pop(0).split()
                        u, o = int(u), int(o)
                        crossings.append((u, o, False, None))
                h = int(lines[0])
                hot = h if h != -1 else None
                self.unpickle(vertices, arrows, crossings)
                self.update_crosspoints()
                return hot
            except ValueError as e:
                tkMessageBox.showwarning(
                    'Bad file',
                    'Failed while parsing line %d' % (num_lines - len(lines)))
            # make sure the window has been rendered before doing anything

    def update_crosspoints(self):
        for arrow in self.Arrows:
            arrow.vectorize()
            arrow.params = self.arrow_params
        for c in self.Crossings:
            c.locate()
        self.Crossings = [c for c in self.Crossings if c.x is not None]
        self.CrossPoints = [Vertex(c.x, c.y, self.canvas, style='hidden')
                            for c in self.Crossings]

    def arrow_components(self, include_isolated_vertices=False, distinguish_closed=False):
        """
        Returns a list of components, given as lists of arrows.
        The closed components are sorted in DT order if they have
        been marked.  The others are sorted by age. If distinguish_closed
        is set to True then two lists are returned, the first has the closed
        components the second has the non-closed components.
        """
        pool = [v.out_arrow for v in self.Vertices if v.in_arrow is None]
        pool += [v.out_arrow for v in self.Vertices if v.in_arrow is not None]
        closed, nonclosed = [], []
        while pool:
            first_arrow = pool.pop(0)
            if first_arrow is None:
                continue
            component = [first_arrow]
            while component[-1].end is not component[0].start:
                next_arrow = component[-1].end.out_arrow
                if next_arrow is None:
                    break
                pool.remove(next_arrow)
                component.append(next_arrow)
            if next_arrow is None:
                nonclosed.append(component)
            else:
                closed.append(component)
        if include_isolated_vertices:
            for vertex in [v for v in self.Vertices if v.is_isolated()]:
                nonclosed.append([Arrow(vertex, vertex, self.canvas,
                                        color=vertex.color)])

        def oldest_vertex(component):
            def oldest(arrow):
                return min([self.Vertices.index(v)
                            for v in [arrow.start, arrow.end] if v])

            return min([len(self.Vertices)] + [oldest(a) for a in component])

        closed.sort(key=lambda x: (x[0].component, oldest_vertex(x)))
        nonclosed.sort(key=oldest_vertex)
        return (closed, nonclosed) if distinguish_closed else closed + nonclosed

    def polylines(self, break_at_overcrossings=True):
        """
        Returns a list of lists of polylines, one per component, that make up
        the drawing of the link diagram.  Each polyline is a maximal
        segment with no undercrossings (e.g. corresponds to a generator
        in the Wirtinger presentation).  Each polyline is a list of
        coordinates [(x0,y0), (x1,y1), ...]  Isolated vertices are
        ignored.

        If the flag break_at_overcrossings is set, each polyline instead
        corresponds to maximal arcs with no crossings on their interior.
        """
        result = []
        self.update_crosspoints()
        segments = {}
        for arrow in self.Arrows:
            arrows_segments = arrow.find_segments(
                self.Crossings,
                include_overcrossings=True)
            segments[arrow] = [[(x0, y0), (x1, y1)]
                               for x0, y0, x1, y1 in arrows_segments]

        if break_at_overcrossings:
            crossing_locations = set([(c.x, c.y) for c in self.Crossings])

        for component in self.arrow_components():
            color = component[1].color
            polylines = []
            polyline = []
            for arrow in component:
                for segment in segments[arrow]:
                    if len(polyline) == 0:
                        polyline = segment
                    elif segment[0] == polyline[-1]:
                        if (break_at_overcrossings and
                                segment[0] in crossing_locations):
                            polylines.append(polyline)
                            polyline = segment
                        else:
                            polyline.append(segment[1])
                    else:
                        polylines.append(polyline)
                        polyline = segment
            polylines.append(polyline)
            if polylines[0][0] == polylines[-1][-1]:
                if len(polylines) > 1:
                    polylines[0] = polylines.pop()[:-1] + polylines[0]
            result.append((polylines, color))
        return result

    def crossing_components(self):
        """
        Returns a list of lists of ECrossings, one per component,
        where the corresponding crossings are ordered consecutively
        through the component.  Requires that all components be closed.
        """
        for vertex in self.Vertices:
            if vertex.is_endpoint():
                raise ValueError('All components must be closed.')
        result = []
        arrow_components = self.arrow_components()
        for component in arrow_components:
            crosses = []
            for arrow in component:
                arrow_crosses = [(c.height(arrow), c, arrow)
                                 for c in self.Crossings if arrow in c]
                arrow_crosses.sort()
                crosses += arrow_crosses
            result.append([ECrossing(c[1], c[2]) for c in crosses])
        return result

    def sorted_components(self):
        """
        Returns a list of crossing components which have been sorted
        and cyclically permuted, following the scheme used in "standard"
        DT codes.

        The sorting process also sets the hit counters on all
        crossings, for use in computing DT and Gauss codes, and
        sets the component attribute of each arrow in each
        component.

        Requires that all components be closed.

        """
        try:
            components = self.crossing_components()[::-1]
        except ValueError:
            return None
        for crossing in self.Crossings:
            crossing.clear_marks()
        # Mark which components each crossing belongs to.
        # if virtual, then do not mark it. keep marks cleared.
        for component in components:
            for ecrossing in component:
                #                if ecrossing.crossing.is_virtual:
                #                    print(component[component.index(ecrossing)])
                #                    del component[component.index(ecrossing)]
                #                    continue
                ecrossing.crossing.mark_component(component)
        sorted_components = []
        count = 0

        while len(components) > 0:
            this_component = components.pop()
            sorted_components.append(this_component)
            # Choose the first crossing on this component by Morwen's
            # rule: If any crossings on this component have been hit,
            # find the first one with an odd label and then start at
            # its predecessor. ignore the virtual crossings
            odd_hits = [ec for ec in this_component if ec.crossing.hit1 % 2 == 1]  # and not ec.crossing.is_virtual
            if len(odd_hits) > 0:
                odd_hits.sort(key=lambda x: x.crossing.hit1)
                n = this_component.index(odd_hits[0])
                this_component = this_component[n - 1:] + this_component[:n - 1]
            # Count the crossings on this component and remember any
            # odd-numbered crossings which are shared with an
            # unfinished component.
            # if virtual, crossing count remains unchanged
            touching = []
            for ec in this_component:
                crossing = ec.crossing
                count += 1
                #                if crossing.is_virtual:
                #                    continue
                if crossing.DT_hit(count, ec):
                    if crossing.comp2 in components:
                        touching.append((crossing, crossing.comp2))
                    elif crossing.comp1 in components:
                        touching.append((crossing, crossing.comp1))
            # Choose the next component, by Morwen's rule: Use the
            # component containing the partner of the first
            # odd-numbered crossing that is shared with another
            # component (if there are any shared crossings).
            if touching:
                touching.sort(key=lambda x: x[0].hit1)
                next_component = touching[0][1]
                components.remove(next_component)
                components.append(next_component)

        return sorted_components

    def SnapPea_KLPProjection(self):
        """
        Constructs a python simulation of a SnapPea KLPProjection
        (Kernel Link Projection) structure.  See Jeff Weeks' SnapPea
        file link_projection.h for definitions.  Here the KLPCrossings
        are modeled by dictionaries.  This method requires that all
        components be closed.  A side effect is that the KLP attributes
        of all crossings are updated.

        The following excerpt from link_projection.h describes the
        main convention:

        If you view a crossing (from above) so that the strands go in the
        direction of the positive x- and y-axes, then the strand going in
        the x-direction is the KLPStrandX, and the strand going in the
        y-direction is the KLPStrandY.  Note that this definition does not
        depend on which is the overstrand and which is the understrand:

        ::

                             KLPStrandY
                                 ^
                                 |
                             ----+---> KLPStrandX
                                 |
                                 |

        \
        """
        try:
            components = self.crossing_components()
        except ValueError:
            return None
        num_crossings = len(self.Crossings)
        num_free_loops = 0
        num_components = len(components)
        id = lambda x: self.Crossings.index(x.crossing)
        for component in components:
            this_component = components.index(component)
            N = len(component)
            for n in range(N):
                this = component[n]
                previous = component[n - 1]
                next = component[(n + 1) % N]
                this.crossing.KLP['sign'] = sign = this.crossing.sign()
                if this.strand == 'X':
                    this.crossing.KLP['Xbackward_neighbor'] = id(previous)
                    this.crossing.KLP['Xbackward_strand'] = previous.strand
                    this.crossing.KLP['Xforward_neighbor'] = id(next)
                    this.crossing.KLP['Xforward_strand'] = next.strand
                    this.crossing.KLP['Xcomponent'] = this_component
                else:
                    this.crossing.KLP['Ybackward_neighbor'] = id(previous)
                    this.crossing.KLP['Ybackward_strand'] = previous.strand
                    this.crossing.KLP['Yforward_neighbor'] = id(next)
                    this.crossing.KLP['Yforward_strand'] = next.strand
                    this.crossing.KLP['Ycomponent'] = this_component
            if N == 0:
                num_free_loops += 1
        KLP_crossings = [crossing.KLP for crossing in self.Crossings]
        return num_crossings, num_free_loops, num_components, KLP_crossings

    def PD_code(self):
        """
        Return the PD (Planar Diagram) code for the link projection,
        as a list of 4-tuples.
        """
        # We view an ecrossing as corresponding to the outgoing arc
        # of the diagram at the ecrossing.crossing.
        dt = self.new_DT(sign=True)
        if dt:
            link = dt.pop()
            new_pd = []
            max_val = 2 * len(dt)
            for crossing in dt:
                a = crossing[0]
                b = crossing[1]
                c = a + 1
                d = b + 1
                if b == max_val:
                    d = 1
                elif a == max_val:
                    c = 1
                # if crossing.sign() == right-handed or left-handed crossing
                if crossing[2] == 'RH':
                    new_pd.append((a, b, c, d))
                else:
                    new_pd.append((a, d, c, b))
            new_pd.append(link)
            return new_pd
        else:
            return None
        try:
            components = self.crossing_components()
        except ValueError:
            return None
        ecrossings = [ec for component in components
                      for ec in component]
        counter = dict((ec, k + 1) for k, ec in enumerate(ecrossings))
        over_dict, under_dict = {}, {}
        for component in components:
            for n, ec in enumerate(component):
                incoming = counter[component[n - 1]]
                outgoing = counter[component[n]]
                D = over_dict if ec.goes_over() else under_dict
                D[ec.crossing] = (incoming, outgoing)
        PD = []
        crossings = [i for i in self.Crossings if not i.is_virtual]
        for crossing in crossings:
            under, over = under_dict[crossing], over_dict[crossing]
            if crossing.sign() == 'RH':
                PD.append((under[0], over[1], under[1], over[0]))
            else:
                PD.append((under[0], over[0], under[1], over[1]))
        return PD

    def test_fcn(self):
        # test DT revised for links
        ecrossing_components = self.crossing_components()
        if ecrossing_components:
            test_dt = [[] for i in range(len(ecrossing_components))]
            new_dt = []
            curr = 0
            visited_crossings = []
            # crossings = sum(ecrossing_components, [])
            for i, crossing in enumerate(self.Crossings):
                visited_crossings.append(crossing)
                num_virtual = 0
                over = None
                under = None
                for num_links, ecrossings in enumerate(ecrossing_components):
                    for ecrossing in ecrossings:
                        curr += 1
                        if ecrossing.crossing.is_virtual:
                            num_virtual += 1
                        else:
                            if over is not None and under is not None:
                                break
                            if ecrossing.crossing == visited_crossings[-1]:

                                if ecrossing.goes_over():
                                    link_num = num_links
                                    over = curr - num_virtual
                                else:
                                    under = curr - num_virtual
                test_dt[link_num].append((over, under))
                new_dt.append((over, under))
                # ecro.crossing.hit1 = new_dt[i][0]
                # ecro.crossing.hit2 = new_dt[i][1]
                curr = 0

        for link in test_dt:
            link.sort(key=min)

        print(f"Test DT:\n{test_dt}\n")

    def new_DT(self, sign=False):
        ecrossing_components = self.crossing_components()
        if ecrossing_components:
            # test_dt = [[] for i in range(len(ecrossing_components))]
            new_dt = []
            # curr is used instead of enums because
            # it can count the total crossings of
            # all ecrossing components (which are numbered
            # in order... we keep track of the labels by the value curr)
            curr = 0
            visited_crossings = []
            link = False
            # go through every crossing, find which labels are under/over,
            # then append as a tuple to our dt convention.
            # crossings are denoted (under, over)
            # print('total crossings:', len(self.Crossings))
            for i, crossing in enumerate(self.Crossings):
                visited_crossings.append(crossing)
                num_virtual = 0
                # link_num = None
                over = None
                under = None
                for num_links, ecrossings in enumerate(ecrossing_components):
                    if num_links > 0: link = True
                    for ecrossing in ecrossings:
                        curr += 1
                        # check if the current crossing is virtual and count it if true
                        # it will count this value more than once, but it is reset at each outer loop
                        if ecrossing.crossing.is_virtual:
                            num_virtual += 1
                        # otherwise, check if over and under are found
                        # if they arent, check if this crossing is the most
                        # recently visited crossing
                        else:
                            if over is not None and under is not None:
                                break
                            if ecrossing.crossing == visited_crossings[-1]:
                                if ecrossing.goes_over():
                                    over = curr - num_virtual
                                else:
                                    under = curr - num_virtual
                # once over and under are found
                # (which is guaranteed, we iterate through every single crossing)
                # append it to our new dt convention
                if sign:
                    new_dt.append((over, under, crossing.sign()))
                else:
                    new_dt.append((over, under))
                crossing.hit1 = new_dt[i][0]
                crossing.hit2 = new_dt[i][1]
                # reset current so that we don't double-count crossings
                curr = 0
        else:
            return None
        # self.test_fcn()

        if sign:
            new_dt = [i for i in new_dt if i[0] is not None and i[1] is not None]
            new_dt.sort(key=lambda x: min(x[0], x[1]))
        else:
            new_dt = [i for i in new_dt if i != (None, None)]
            new_dt.sort(key=min)

        # print(new_dt, sep='\n\n')

        # self.test_fcn()
        new_dt.append(link)
        if link:
            return new_dt

        return new_dt

    def DT_code(self, alpha=False, signed=True, return_sizes=False):
        """
        Return the Dowker-Thistlethwaite code as a list of tuples of
        even integers.  Requires that all components be closed.

        If alpha is set to True, this method returns the alphabetical
        Dowker-Thistlethwaite code as used in Oliver Goodman's Snap
        and in the tabulations by Jim Hoste and Morwen Thistlethwaite.

        If return_sizes is set to True, a list of the number of crossings
        in each component is returned (this is for use by Gauss_code).
        """
        sorted_components = self.sorted_components()
        if sorted_components is None or len(sorted_components) == 0:
            return (None, None) if return_sizes else None
        component_sizes = [len(c) for c in sorted_components]
        DT_chunks, S = [], 0
        for size in component_sizes:
            DT_chunks.append((size + 1) // 2 if S % 2 != 0 else size // 2)
            S += size
        # Now build the Dowker-Thistlethwaite code
        even_codes = [None] * len(self.Crossings)
        flips = [None] * len(self.Crossings)
        for crossing in self.Crossings:
            #            if crossing.is_virtual:
            #                continue
            if crossing.hit1 % 2 != 0:
                n = (crossing.hit1 - 1) // 2
                even_codes[n] = crossing.hit2
            else:
                if crossing.hit2 == -2 * len(self.Crossings):
                    # This can actually happen!
                    n = -1
                else:
                    n = (crossing.hit2 - 1) // 2
                even_codes[n] = crossing.hit1
            flips[n] = int(crossing.flipped) if crossing.flipped is not None else None
        if not alpha:
            dt = []
            for chunk in DT_chunks:
                dt.append(tuple(i for i in even_codes[:chunk] if i is not None))
                even_codes = even_codes[chunk:]
            result = [dt]
            if signed:
                result.append([i for i in flips if i is not None])
        else:
            prefix_ints = [len(self.Crossings), len(sorted_components)]
            prefix_ints += DT_chunks
            if prefix_ints[0] > 26:
                tkMessageBox.showwarning(
                    'Error',
                    'Alphabetical DT codes require fewer than 26 crossings.')
                return None
            alphacode = ''.join(tuple([DT_alphabet[n >> 1] for n in even_codes]))
            prefix = ''.join(tuple([DT_alphabet[n] for n in prefix_ints]))
            if signed:
                alphacode += '.' + ''.join([str(f) for f in flips])
            result = [prefix + alphacode]
        if return_sizes:
            result.append(component_sizes)
        return tuple(result)

    def new_Gauss(self):
        dt = self.new_DT()
        link = dt.pop()
        gauss = []
        # gauss = [0 for i in range(2*len(dt))]
        # seems to work, also has proper signs :)
        # iterates from 1 to twice the num of crossings
        # finds chronological order of crossings, takes the min
        # but keeps the sign of the current i value ie.
        # DT (2, 5) if i == 5 will give gauss of -2
        for i in range(1, (len(dt) * 2) + 1):
            for crossing in dt:
                if i in crossing:
                    temp = min(crossing)
                    if i == crossing[1]:
                        temp *= -1
                    gauss.append(temp)
        # gauss = [i if i < int(len(gauss)/2) else i-1 for i in gauss]

        # count consecutive gauss, decrease each value greater than pivot by ++1 for each cycle over the reference
        # then increase the reference at each step.
        # add item to help menu 'convention' menu that explains virtual DT, Gauss, PD
        # this all works, just has some +1/-1 issue somewhere in the iterations...
        pivot = None
        fixed_gauss = gauss.copy()

        def count_cycle(splice, ind):
            cycle = 0
            for c in splice:
                for j in splice[splice.index(c):]:
                    if abs(j) == abs(c) and j != c:
                        cycle += 1
            print('before\n', gauss[ind:])
            back_splice = update_gauss(cycle, gauss[ind:])
            print(back_splice)
            return cycle, back_splice

        def update_gauss(cycles, splice):
            tmp = []
            for c in splice:
                if abs(c) > pivot + cycles:
                    if c > 0:
                        c -= 1
                    else:
                        c += 1
                tmp.append(c)
            return tmp

        for i, code in enumerate(gauss):
            if i == 0:
                continue
            if abs(code) == abs(gauss[i - 1]) + 1:
                continue
            else:
                if pivot is None:
                    pivot = abs(gauss[i - 1])
                if pivot:
                    cyc, tail = count_cycle(gauss[:i+1], i)
                    gauss = gauss[:i] + tail
                print(f"nonconsecutive at {code}, cycles:{cyc}, pivot:{pivot+cyc}")

        gauss.append(link)

        return gauss

    def Gauss_code(self):
        """
        Return a Gauss code for the link.  The Gauss code is computed
        from a DT code, so the Gauss code will use the same indexing
        of crossings as is used for the DT code.  Requires that all
        components be closed.
        """
        return self.new_Gauss()
        dt, sizes = self.DT_code(signed=False, return_sizes=True)
        if dt is None:
            return None
        evens = [y for x in dt for y in x]
        size = 2 * len(evens)
        counts = [None] * size
        for odd, N in zip(range(1, size, 2), evens):
            even = abs(N)
            if even < odd:
                counts[even - 1] = -N
                counts[odd - 1] = N
            else:
                O = odd if N > 0 else -odd
                counts[even - 1] = -O
                counts[odd - 1] = O
        gauss = []
        start = 0
        for size in sizes:
            end = start + size
            gauss.append(tuple(counts[start:end]))
            start = end
        return gauss

    def BB_framing(self):
        """
        Return the standard meridian-longitude coordinates of the
        blackboard longitude (i.e. the peripheral element obtained
        by following the top of a tubular neighborhood of the knot).
        """
        try:
            components = self.crossing_components()
        except ValueError:
            return None
        framing = []
        for component in components:
            m = 0
            for ec in component:
                crossing = ec.crossing
                # Only consider self crossings
                if crossing.comp1 == crossing.comp2 == component:
                    if ec.crossing.sign() == 'RH':
                        m += 1
                    elif ec.crossing.sign() == 'LH':
                        m -= 1
            # Each crossing got counted twice.
            framing.append((m // 2, 1))
        return framing

    def write_text(self, text):
        # Subclasses override this
        pass

    def DT_normal(self):
        """
        Displays a Dowker-Thistlethwaite code as a list of tuples of
        signed even integers.
        """
        code = self.DT_code()
        if code:
            self.write_text(('DT: %s,  %s' % code).replace(', ', ','))

    def DT_alt(self):
        """
            Displays a Dowker-Thistlethwaite code as a list of tuples
            as (over-label, under-label) for each crossing
        """
        code = self.new_DT()
        link = code.pop()
        if code:
            if link:
                self.write_text("Virtual Links are a WIP: " + ('DT: %s' % code).replace(', ', ','))
            else:
                self.write_text(('DT: %s' % code).replace(', ', ','))

    def DT_alpha(self):
        """
        Displays an alphabetical Dowker-Thistlethwaite code, as used in
        the knot tabulations.
        """
        code = self.DT_code(alpha=True)
        if code:
            self.write_text('DT: %s' % code)

    def Gauss_info(self):
        """
        Displays a Gauss code as a list of tuples of signed
        integers.
        """
        code = self.Gauss_code()
        link = code.pop()
        if code:
            if link:
                self.write_text("Virtual Links are a WIP: " + ('Gauss: %s' % code).replace(', ', ','))
            else:
                self.write_text(('Gauss: %s' % code).replace(', ', ','))

    def PD_info(self):
        """
        Displays a PD code as a list of 4-tuples.
        """
        code = self.PD_code()
        link = code.pop()
        if code:
            if link:
                self.write_text("Virtual Links are a WIP: " + ('PD: %s' % code).replace(', ', ','))
            else:
                self.write_text(('PD: %s' % code).replace(', ', ','))

    def BB_info(self):
        """
        Displays the meridian-longitude coordinates of the blackboard
        longitudes of the components of the link
        """
        framing = self.BB_framing()
        if framing:
            self.write_text(('BB framing:  %s' % framing).replace(', ', ','))

    def SnapPea_projection_file(self):
        """
        Returns a string containing the contents of a SnapPea link
        projection file.
        """
        has_virtual_crossings = any(crossing.is_virtual for crossing in self.Crossings)

        result = ''
        result += '% Virtual Link Projection\n' if has_virtual_crossings else '% Link Projection\n'
        components = self.arrow_components()
        result += '%d\n' % len(components)
        for component in components:
            first = self.Vertices.index(component[0].start)
            last = self.Vertices.index(component[-1].end)
            result += '%4.1d %4.1d\n' % (first, last)
        result += '%d\n' % len(self.Vertices)
        for vertex in self.Vertices:
            result += '%5.1d %5.1d\n' % vertex.point()
        result += '%d\n' % len(self.Arrows)
        for arrow in self.Arrows:
            start_index = self.Vertices.index(arrow.start)
            end_index = self.Vertices.index(arrow.end)
            result += '%4.1d %4.1d\n' % (start_index, end_index)
        result += '%d\n' % len(self.Crossings)
        for crossing in self.Crossings:
            under = self.Arrows.index(crossing.under)
            over = self.Arrows.index(crossing.over)
            is_virtual = 'v' if crossing.is_virtual else 'r'
            result += '%4s %4.1d %4.1d\n' % (is_virtual, under, over) if has_virtual_crossings else '%4.1d %4.1d\n' % (
                under, over)
        if self.ActiveVertex:
            result += '%d\n' % self.Vertices.index(self.ActiveVertex)
        else:
            result += '-1\n'
        return result

    def twister_surface_file(self):
        """
        Returns a string containing the contents of a Twister surface
        file. Raises a ValueError if there are no virtual crossings.
        """
        result = '# A Twister surface file produced by PLink.\n'
        virtual_crossings = [crossing for crossing in self.Crossings if crossing.is_virtual]
        if len(virtual_crossings) == 0:
            raise ValueError('No virtual crossings present.')
        closed_components, nonclosed_components = self.arrow_components(distinguish_closed=True)

        def component_sequence(component):
            sequence = []
            for arrow in component:
                this_arrows_crossings = []
                for index, virtual_crossing in enumerate(virtual_crossings):
                    if arrow == virtual_crossing.under:
                        other_arrow = virtual_crossing.over
                    elif arrow == virtual_crossing.over:
                        other_arrow = virtual_crossing.under
                    else:
                        continue
                    sign = (arrow.dx * other_arrow.dy - arrow.dy * other_arrow.dx > 0)
                    this_arrows_crossings.append(
                        (arrow ^ other_arrow, index, '+' if sign else '-'))
                this_arrows_crossings.sort()
                sequence += [pm + str(index) for _, index, pm in this_arrows_crossings]
            return sequence

        curves = list(ascii_lowercase) + ['%s%d' % (letter, index)
                                          for index in range((len(closed_components) + len(nonclosed_components)) // 26)
                                          for letter in ascii_lowercase]
        i = 0
        for component in closed_components:
            result += 'annulus,%s,%s,%s#\n' % (
                curves[i], curves[i].swapcase(), ','.join(component_sequence(component)))
            i += 1
        for component in nonclosed_components:
            result += 'rectangle,%s,%s,%s#\n' % (
                curves[i], curves[i].swapcase(), ','.join(component_sequence(component)))
            i += 1
        return result

    def save_as_tikz(self, file_name, colormode='color', width=282.0):
        polylines = self.polylines(break_at_overcrossings=True)
        colors = [polyline[-1] for polyline in polylines]
        tikz = TikZPicture(self.canvas, colors, width)
        for polyline in polylines:
            for line in polyline[0]:
                points = ['(%.2f, %.2f)' % tikz.transform(xy) for xy in line]
                tikz.write(polyline[1],
                           '    \\draw ' + ' -- '.join(points) + ';\n')
        tikz.save(file_name)

    def unpickle(self, vertices, arrows, crossings, hot=None):
        """
        Builds a link diagram from the following data:
           * vertices: a list of (x,y)-coordinates for the vertices;

           * arrows: a list of pairs of integers (start, end), giving
           the indices in the vertex list of the endpoints of each arrow;

           * crossings: a list of quadruples (under, over, is_virtual, label),
           giving the indices in the arrow list of each pair of crossing
           arrows, a boolean indicating if the crossing is virtual,
           and an assigned label.

           * an optional argument "hot" giving the index of one vertex
           which was being added at the time the diagram was pickled
        """
        for x, y in vertices:
            X, Y = float(x), float(y)
            self.Vertices.append(Vertex(X, Y, self.canvas))
        for start, end in arrows:
            S, E = self.Vertices[int(start)], self.Vertices[int(end)]
            self.Arrows.append(Arrow(S, E, self.canvas))
        for under, over, is_virtual, label in crossings:
            U, O, V, L = self.Arrows[int(under)], self.Arrows[int(over)], bool(is_virtual), str(label)
            self.Crossings.append(Crossing(O, U, V, L))

    def pickle(self):
        """
        Inverse of unpickle.
        """
        V = lambda v: self.Vertices.index(v)
        A = lambda a: self.Arrows.index(a)
        vertices = [(v.x, v.y) for v in self.Vertices]
        arrows = [(V(a.start), V(a.end)) for a in self.Arrows]
        crossings = [(A(c.under), A(c.over), c.is_virtual, c.label) for c in self.Crossings]
        hot = V(self.ActiveVertex) if self.ActiveVertex else None
        return [vertices, arrows, crossings, hot]

    def create_colors(self):
        components = self.arrow_components()
        for component in components:
            color = self.palette.new()
            component[0].start.set_color(color)
            for arrow in component:
                arrow.set_color(color)
                arrow.end.set_color(color)

    def color_first(self):
        crossing_comps = self.crossing_components()
        for ecrossings in crossing_comps:
            for i, ecrossing in enumerate(ecrossings):
                if ecrossing.crossing.is_virtual:
                    continue
                if ecrossing.crossing.hit1 == 1:
                    self.full_redraw()
                    ecrossing.crossing.over.set_color('black')
                    return
                elif ecrossing.crossing.hit2 == 1:
                    self.full_redraw()
                    ecrossing.crossing.under.set_color('black')
                    return
