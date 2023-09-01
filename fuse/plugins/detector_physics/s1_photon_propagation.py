import numpy as np
import strax
import straxen
import nestpy
import logging

from ...common import init_spe_scaling_factor_distributions, pmt_transition_time_spread, build_photon_propagation_output, FUSE_PLUGIN_TIMEOUT

export, __all__ = strax.exporter()

logging.basicConfig(handlers=[logging.StreamHandler()])
log = logging.getLogger('fuse.detector_physics.s1_photon_propagation')

#Initialize the nestpy random generator
#The seed will be set in the setup function
nest_rng = nestpy.RandomGen.rndm()

@export
class S1PhotonPropagationBase(strax.Plugin):
    
    __version__ = "0.1.0"
    
    depends_on = ("s1_photons", "microphysics_summary")
    provides = "propagated_s1_photons"
    data_kind = "S1_photons"
    
    #dtype is the same for S1 and S2
    
    #Forbid rechunking
    rechunk_on_save = False

    save_when = strax.SaveWhen.TARGET

    input_timeout = FUSE_PLUGIN_TIMEOUT

    dtype = [('channel', np.int16),
             ('dpe', np.bool_),
             ('photon_gain', np.int32),
            ]
    dtype = dtype + strax.time_fields

    #Config options shared by S1 and S2 simulation 
    debug = straxen.URLConfig(
        default=False, type=bool,track=False,
        help='Show debug informations',
    )

    p_double_pe_emision = straxen.URLConfig(
        type=(int, float),
        help='p_double_pe_emision',
    )

    pmt_transit_time_spread = straxen.URLConfig(
        type=(int, float),
        help='pmt_transit_time_spread',
    )

    pmt_transit_time_mean = straxen.URLConfig(
        type=(int, float),
        help='pmt_transit_time_mean',
    )

    pmt_circuit_load_resistor = straxen.URLConfig(
        type=(int, float),
        help='pmt_circuit_load_resistor',
    )

    digitizer_bits = straxen.URLConfig(
        type=(int, float),
        help='digitizer_bits',
    )

    digitizer_voltage_range = straxen.URLConfig(
        type=(int, float),
        help='digitizer_voltage_range',
    )

    n_top_pmts = straxen.URLConfig(
        type=(int),
        help='Number of PMTs on top array',
    )

    n_tpc_pmts = straxen.URLConfig(
        type=(int),
        help='Number of PMTs in the TPC',
    )

    gains = straxen.URLConfig(
        cache=True,
        help='pmt gains',
    )

    photon_area_distribution = straxen.URLConfig(
        cache=True,
        help='photon_area_distribution',
    )

    #Config options specific to S1 simulation
    s1_pattern_map = straxen.URLConfig(
        cache=True,
        help='s1_pattern_map',
    )

    deterministic_seed = straxen.URLConfig(
        default=True, type=bool,
        help='Set the random seed from lineage and run_id, or pull the seed from the OS.',
    )
    
    def setup(self):

        if self.debug:
            log.setLevel('DEBUG')
            log.debug(f"Running S1PhotonPropagation version {self.__version__} in debug mode")
        else: 
            log.setLevel('WARNING')

        if self.deterministic_seed:
            hash_string = strax.deterministic_hash((self.run_id, self.lineage))
            seed = int(hash_string.encode().hex(), 16)
            #Dont know but nestpy seems to have a problem with large seeds
            self.short_seed = int(repr(seed)[-8:])
            nest_rng.set_seed(self.short_seed)
            self.rng = np.random.default_rng(seed = seed)
            log.debug(f"Generating random numbers from seed {seed}")
            log.debug(f"Generating nestpy random numbers from seed {self.short_seed}")
        else: 
            log.debug(f"Generating random numbers with seed pulled from OS")

        self.pmt_mask = np.array(self.gains) > 0  # Converted from to pe (from cmt by default)
        self.turned_off_pmts = np.arange(len(self.gains))[np.array(self.gains) == 0]
        
        #I dont like this part -> clean up before merging the PR
        self._cached_uniform_to_pe_arr = {}
        self.__uniform_to_pe_arr = init_spe_scaling_factor_distributions(self.photon_area_distribution)

    def compute(self, interactions_in_roi):

        #Just apply this to clusters with photons hitting a PMT
        instruction = interactions_in_roi[interactions_in_roi["n_s1_photon_hits"] > 0]

        if len(instruction) == 0:
            return np.zeros(0, self.dtype)
        
        t = instruction['time']
        x = instruction['x']
        y = instruction['y']
        z = instruction['z']
        n_photons = instruction['photons'].astype(np.int64)
        recoil_type = instruction['nestid']
        positions = np.array([x, y, z]).T  # For map interpolation
        
        # The new way interpolation is written always require a list
        _photon_channels = self.photon_channels(positions=positions,
                                                n_photon_hits=instruction["n_s1_photon_hits"],
                                                )
 
        _photon_timings = self.photon_timings(t=t,
                                              n_photon_hits=instruction["n_s1_photon_hits"],
                                              recoil_type=recoil_type,
                                              channels=_photon_channels,
                                              positions=positions,
                                              e_dep = instruction['ed'],
                                              n_photons_emitted = n_photons,
                                              n_excitons = instruction['excitons'].astype(np.int64), 
                                              local_field = instruction['e_field'],
                                             )
        
        #I should sort by time i guess
        sortind = np.argsort(_photon_timings)
        _photon_channels = _photon_channels[sortind]
        _photon_timings = _photon_timings[sortind]

        #Do i want to save both -> timings with and without pmt transition time spread?
        # Correct for PMT Transition Time Spread (skip for pmt after-pulses)
        # note that PMT datasheet provides FWHM TTS, so sigma = TTS/(2*sqrt(2*log(2)))=TTS/2.35482
        _photon_timings, _photon_gains, _photon_is_dpe = pmt_transition_time_spread(
            _photon_timings=_photon_timings,
            _photon_channels=_photon_channels,
            pmt_transit_time_mean=self.pmt_transit_time_mean,
            pmt_transit_time_spread=self.pmt_transit_time_spread,
            p_double_pe_emision=self.p_double_pe_emision,
            gains=self.gains,
            __uniform_to_pe_arr=self.__uniform_to_pe_arr,
            rng=self.rng,
            )

        result = build_photon_propagation_output(
            dtype=self.dtype,
            _photon_timings=_photon_timings,
            _photon_channels=_photon_channels,
            _photon_gains=_photon_gains,
            _photon_is_dpe=_photon_is_dpe,
            )

        result = strax.sort_by_time(result)

        return result
    
    def photon_channels(self, positions, n_photon_hits):
        """Calculate photon arrival channels
        :params positions: 2d array with xy positions of interactions
        :params n_photon_hits: 1d array of ints with number of photon hits to simulate
        :params config: dict wfsim config
        :params s1_pattern_map: interpolator instance of the s1 pattern map
        returns nested array with photon channels   
        """
        channels = np.arange(self.n_tpc_pmts)  # +1 for the channel map
        p_per_channel = self.s1_pattern_map(positions)
        p_per_channel[:, np.in1d(channels, self.turned_off_pmts)] = 0

        _photon_channels = []
        for ppc, n in zip(p_per_channel, n_photon_hits):
            _photon_channels.append(
                self.rng.choice(
                    channels,
                    size=n,
                    p=ppc / np.sum(ppc),
                    replace=True))

        return np.concatenate(_photon_channels)

    def photon_timings(self):
        raise NotImplementedError # To be implemented by child class
        

@export
class S1PhotonPropagation(S1PhotonPropagationBase):
    """
    This class is used to simulate the propagation of photons from an S1 signal using
    optical propagation and luminescence timing from nestpy
    """

    __version__ = "0.1.0"

    child_plugin = True

    maximum_recombination_time = straxen.URLConfig(
        type=(int, float),
        help='maximum_recombination_time',
    )

    s1_optical_propagation_spline = straxen.URLConfig(
        cache=True,
        help='s1_optical_propagation_spline',
    )

    def setup(self):
        super().setup()

        log.info('Using NEST for scintillation time without set calculator\n'
                 'Creating new nestpy calculator')
        self.nestpy_calc = nestpy.NESTcalc(nestpy.DetectorExample_XENON10())

    def photon_timings(self,
                       t,
                       n_photon_hits,
                       recoil_type,
                       channels,
                       positions,
                       e_dep,
                       n_photons_emitted,
                       n_excitons, 
                       local_field,
                      ):
        """Calculate distribution of photon arrival timnigs
        :param t: 1d array of ints
        :param n_photon_hits: number of photon hits, 1d array of ints
        :param recoil_type: 1d array of ints
        :param config: dict wfsim config
        :param channels: list of photon hit channels 
        :param positions: nx3 array of true XYZ positions from instruction
        :param e_dep: energy of the deposit, 1d float array
        :param n_photons_emitted: number of orignally emitted photons/quanta, 1d int array
        :param n_excitons: number of exctions in deposit, 1d int array
        :param local_field: local field in the point of the deposit, 1d array of floats
        returns photon timing array"""
        _photon_timings = np.repeat(t, n_photon_hits)
        _n_hits_total = len(_photon_timings)

        z_positions = np.repeat(positions[:, 2], n_photon_hits)
        
        #Propagation Modeling
        _photon_timings += self.optical_propagation(channels,
                                                    z_positions,
                                                    ).astype(np.int64)

        #Scintillation Modeling
        counts_start = 0
        for i, counts in enumerate(n_photon_hits):

            # Allow overwriting with "override_s1_photon_time_field"
            # xenon:j_angevaare:wfsim_photon_timing_bug
            #_local_field = config.get('override_s1_photon_time_field', local_field[i])
            #_local_field = (_local_field if _local_field >0 else local_field[i])
            _local_field = local_field[i]
            scint_time = self.nestpy_calc.GetPhotonTimes(
                nestpy.INTERACTION_TYPE(recoil_type[i]),
                n_photons_emitted[i],
                 n_excitons[i],
                 _local_field,
                 e_dep[i]
                 )

            scint_time = np.clip(scint_time, 0, self.maximum_recombination_time)

            # The first part of the scint_time is from exciton only, see
            # https://github.com/NESTCollaboration/nestpy/blob/fe3d5d7da5d9b33ac56fbea519e02ef55152bc1d/src/nestpy/NEST.cpp#L164-L179
            _photon_timings[counts_start: counts_start + counts] += \
               self.rng.choice(scint_time, counts, replace=False).astype(np.int64)

            counts_start += counts

        return _photon_timings
    
    def optical_propagation(self, channels, z_positions):
        """Function gettting times from s1 timing splines:
        :param channels: The channels of all s1 photon
        :param z_positions: The Z positions of all s1 photon
        """
        assert len(z_positions) == len(channels), 'Give each photon a z position'

        prop_time = np.zeros_like(channels)
        z_rand = np.array([z_positions, self.rng.random(len(channels))]).T

        is_top = channels < self.n_top_pmts
        prop_time[is_top] = self.s1_optical_propagation_spline(z_rand[is_top], map_name='top')

        is_bottom = channels >= self.n_top_pmts
        prop_time[is_bottom] = self.s1_optical_propagation_spline(z_rand[is_bottom], map_name='bottom')

        return prop_time
