import strax
import straxen
import numpy as np
import logging

from numba import njit
from scipy.stats import skewnorm
from scipy import constants

export, __all__ = strax.exporter()

from ...common import FUSE_PLUGIN_TIMEOUT, pmt_gains
from ...common import init_spe_scaling_factor_distributions, pmt_transit_time_spread, photon_gain_calculation 
from ...common import build_photon_propagation_output

logging.basicConfig(handlers=[logging.StreamHandler()])
log = logging.getLogger('fuse.detector_physics.s2_photon_propagation')

conversion_to_bar = 1/constants.elementary_charge / 1e1

@export
class S2PhotonPropagationBase(strax.DownChunkingPlugin):
    
    __version__ = "0.1.4"
    
    depends_on = ("electron_time","s2_photons", "extracted_electrons", "drifted_electrons", "s2_photons_sum")
    provides = "propagated_s2_photons"
    data_kind = "S2_photons"

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
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=p_double_pe_emision",
        type=(int, float),
        cache=True,
        help='p_double_pe_emision',
    )

    pmt_transit_time_spread = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=pmt_transit_time_spread",
        type=(int, float),
        cache=True,
        help='pmt_transit_time_spread',
    )

    pmt_transit_time_mean = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=pmt_transit_time_mean",
        type=(int, float),
        cache=True,
        help='pmt_transit_time_mean',
    )

    pmt_circuit_load_resistor = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=pmt_circuit_load_resistor",
        type=(int, float),
        cache=True,
        help='pmt_circuit_load_resistor',
    )

    digitizer_bits = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=digitizer_bits",
        type=(int, float),
        cache=True,
        help='digitizer_bits',
    )

    digitizer_voltage_range = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=digitizer_voltage_range",
        type=(int, float),
        cache=True,
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

    gain_model_mc = straxen.URLConfig(
        default="cmt://to_pe_model?version=ONLINE&run_id=plugin.run_id",
        infer_type=False,
        help='PMT gain model',
    )

    photon_area_distribution = straxen.URLConfig(
        default = 'simple_load://resource://simulation_config://'
                  'SIMULATION_CONFIG_FILE.json?'
                  '&key=photon_area_distribution'
                  '&fmt=csv',
        cache=True,
        help='photon_area_distribution',
    )

    #Config options specific to S2 simulation
    phase_s2 = straxen.URLConfig(
        default="gas",
        help='phase of the s2 producing region',
    )

    drift_velocity_liquid = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=drift_velocity_liquid",
        type=(int, float),
        cache=True,
        help='Drift velocity of electrons in the liquid xenon',
    )

    tpc_length = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=tpc_length",
        type=(int, float),
        cache=True,
        help='Length of the XENONnT TPC',
    )

    tpc_radius = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=tpc_radius",
        type=(int, float),
        cache=True,
        help='Radius of the XENONnT TPC ',
    )

    diffusion_constant_transverse = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=diffusion_constant_transverse",
        type=(int, float),
        cache=True,
        help='Transverse diffusion constant',
    )

    s2_aft_skewness = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=s2_aft_skewness",
        type=(int, float),
        cache=True,
        help='Skew of the S2 area fraction top',
    )

    s2_aft_sigma = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=s2_aft_sigma",
        type=(int, float),
        cache=True,
        help='Width of the S2 area fraction top',
    )
    
    enable_field_dependencies = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=enable_field_dependencies",
        cache=True,
        help='enable_field_dependencies',
    )

    s2_mean_area_fraction_top = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=s2_mean_area_fraction_top",
        type=(int, float),
        cache=True,
        help='Mean S2 area fraction top',
    )
    
    s2_pattern_map = straxen.URLConfig(
        default = 's2_aft_scaling://pattern_map://resource://simulation_config://'
                  'SIMULATION_CONFIG_FILE.json?'
                  '&key=s2_pattern_map'
                  '&fmt=pkl'
                  '&pmt_mask=plugin.pmt_mask'
                  '&s2_mean_area_fraction_top=plugin.s2_mean_area_fraction_top'
                  '&n_tpc_pmts=plugin.n_tpc_pmts'
                  '&n_top_pmts=plugin.n_top_pmts'
                  ,
        cache=True,
        help='S2 pattern map',
    )

    #stupid naming problem...
    field_dependencies_map_tmp = straxen.URLConfig(
        default = 'itp_map://resource://simulation_config://'
                  'SIMULATION_CONFIG_FILE.json?'
                  '&key=field_dependencies_map'
                  '&fmt=json.gz'
                  '&method=RectBivariateSpline',
        cache=True,
        help='Map for the electric field dependencies',
    )

    singlet_fraction_gas = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=singlet_fraction_gas",
        type=(int, float),
        cache=True,
        help='Fraction of singlet states in GXe',
    )

    triplet_lifetime_gas = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=triplet_lifetime_gas",
        type=(int, float),
        cache=True,
        help='Liftetime of triplet states in GXe',
    )

    singlet_lifetime_gas = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=singlet_lifetime_gas",
        type=(int, float),
        cache=True,
        help='Liftetime of singlet states in GXe',
    )

    triplet_lifetime_liquid = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=triplet_lifetime_liquid",
        type=(int, float),
        cache=True,
        help='Liftetime of triplet states in LXe',
    )

    singlet_lifetime_liquid = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=singlet_lifetime_liquid",
        type=(int, float),
        cache=True,
        help='Liftetime of singlet states in LXe',
    )

    s2_secondary_sc_gain_mc = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=s2_secondary_sc_gain",
        type=(int, float),
        cache=True,
        help='Secondary scintillation gain',
    )

    propagated_s2_photons_file_size_target = straxen.URLConfig(
        type=(int, float), default = 500, track=False,
        help='target for the propagated_s2_photons file size in MB',
    )

    min_electron_gap_length_for_splitting = straxen.URLConfig(
        type=(int, float), default = 1e5, track=False,
        help='chunk can not be split if gap between photons is smaller than this value given in ns',
    )

    deterministic_seed = straxen.URLConfig(
        default=True, type=bool,
        help='Set the random seed from lineage and run_id, or pull the seed from the OS.',
    )

    def setup(self):

        if self.debug:
            log.setLevel('DEBUG')
            log.debug(f"Running S2PhotonPropagation version {self.__version__} in debug mode")
        else: 
            log.setLevel('INFO')

        if self.deterministic_seed:
            hash_string = strax.deterministic_hash((self.run_id, self.lineage))
            seed = int(hash_string.encode().hex(), 16)
            self.rng = np.random.default_rng(seed = seed)
            log.debug(f"Generating random numbers from seed {seed}")
        else: 
            self.rng = np.random.default_rng()
            log.debug(f"Generating random numbers with seed pulled from OS")

        #Set the random generator for scipy
        skewnorm.random_state=self.rng
        
        self.gains = pmt_gains(self.gain_model_mc,
                               digitizer_voltage_range=self.digitizer_voltage_range,
                               digitizer_bits=self.digitizer_bits,
                               pmt_circuit_load_resistor=self.pmt_circuit_load_resistor
                               )

        self.pmt_mask = np.array(self.gains) > 0  # Converted from to pe (from cmt by default)
        self.turned_off_pmts = np.arange(len(self.gains))[np.array(self.gains) == 0]

        self.spe_scaling_factor_distributions = init_spe_scaling_factor_distributions(self.photon_area_distribution)

        #Move this part into a nice URLConfig protocol?
        # Field dependencies 
        if any(self.enable_field_dependencies.values()):
            self.drift_velocity_scaling = 1.0
            # calculating drift velocity scaling to match total drift time for R=0 between cathode and gate
            if "norm_drift_velocity" in self.enable_field_dependencies.keys():
                if self.enable_field_dependencies['norm_drift_velocity']:
                    norm_dvel = self.field_dependencies_map_tmp(np.array([ [0], [- self.tpc_length]]).T, map_name='drift_speed_map')[0]
                    norm_dvel*=1e-4
                    self.drift_velocity_scaling = self.drift_velocity_liquid/norm_dvel
            def rz_map(z, xy, **kwargs):
                r = np.sqrt(xy[:, 0]**2 + xy[:, 1]**2)
                return self.field_dependencies_map_tmp(np.array([r, z]).T, **kwargs)
            self.field_dependencies_map = rz_map

    def compute(self, individual_electrons, interactions_in_roi, start, end):

        #Just apply this to clusters with photons
        mask = interactions_in_roi["n_electron_extracted"] > 0

        if len(individual_electrons) == 0:
            yield self.chunk(start=start, end=end, data=np.zeros(0, dtype=self.dtype))
            return
            
        #Split into "sub-chunks"
        electron_time_gaps = individual_electrons["time"][1:] - individual_electrons["time"][:-1] 
        electron_time_gaps = np.append(electron_time_gaps, 0) #Add last gap

        #Index to match the electrons to the corresponding interaction_in_roi (and vice versa)
        #electron_index = build_electron_index(individual_electrons, interactions_in_roi[mask])
        #electron_index = individual_electrons["order_index"]

        split_index = find_electron_split_index(
            individual_electrons,
            electron_time_gaps,
            file_size_limit = self.propagated_s2_photons_file_size_target,
            min_gap_length = self.min_electron_gap_length_for_splitting,
            mean_n_photons_per_electron = self.s2_secondary_sc_gain_mc
            )

        electron_chunks = np.array_split(individual_electrons, split_index)
        #index_chunks = np.array_split(electron_index, split_index)

        n_chunks = len(electron_chunks)
        if n_chunks > 1:
            log.info("Chunk size exceeding file size target.")
            log.info("Downchunking to %d chunks" % n_chunks)
        
        last_start = start
        if n_chunks>1:
            #for electron_group, index_group in zip(electron_chunks[:-1], index_chunks[:-1]):
            for electron_group in electron_chunks[:-1]:
                interactions_chunk = interactions_in_roi[mask][np.unique(electron_group["order_index"])]
                #interactions_chunk = interactions_in_roi[mask][np.min(index_group):np.max(index_group)+1]
                positions = np.array([interactions_chunk["x_obs"], interactions_chunk["y_obs"]]).T

                _photon_channels = self.photon_channels(interactions_chunk["n_electron_extracted"],
                                                        interactions_chunk["z_obs"],
                                                        positions,
                                                        interactions_chunk["drift_time_mean"] ,
                                                        interactions_chunk["sum_s2_photons"],
                                                    )
                
                _photon_timings = self.photon_timings(positions,
                                                    interactions_chunk["sum_s2_photons"],
                                                    _photon_channels,
                                                    )
        
                #repeat for n photons per electron # Should this be before adding delays?
                _photon_timings += np.repeat(electron_group["time"], electron_group["n_s2_photons"])
                
                #Do i want to save both -> timings with and without pmt transit time spread?
                # Correct for PMT Transit Time Spread 
                _photon_timings = pmt_transit_time_spread(_photon_timings=_photon_timings,
                                                          pmt_transit_time_mean=self.pmt_transit_time_mean,
                                                          pmt_transit_time_spread=self.pmt_transit_time_spread,
                                                          rng=self.rng,
                                                          )

                _photon_gains, _photon_is_dpe = photon_gain_calculation(_photon_channels=_photon_channels,
                                                                        p_double_pe_emision=self.p_double_pe_emision,
                                                                        gains=self.gains,
                                                                        spe_scaling_factor_distributions=self.spe_scaling_factor_distributions,
                                                                        rng=self.rng,
                                                                        )

                result = build_photon_propagation_output(dtype=self.dtype,
                                                         _photon_timings=_photon_timings,
                                                         _photon_channels=_photon_channels,
                                                         _photon_gains=_photon_gains,
                                                         _photon_is_dpe=_photon_is_dpe,
                                                         )

                result = strax.sort_by_time(result)

                #move the chunk bound 90% of the minimal gap length to the next photon to make space for afterpluses
                chunk_end = np.max(strax.endtime(result)) + np.int64(self.min_electron_gap_length_for_splitting*0.9)
                chunk = self.chunk(start=last_start, end=chunk_end, data=result)
                last_start = chunk_end
                yield chunk
    
        #And the last chunk
        interactions_chunk = interactions_in_roi[mask][np.unique(electron_chunks[-1]["order_index"])]
        #interactions_chunk = interactions_in_roi[mask][np.min(index_chunks[-1]):np.max(index_chunks[-1])+1]
        positions = np.array([interactions_chunk["x_obs"], interactions_chunk["y_obs"]]).T

        _photon_channels = self.photon_channels(interactions_chunk["n_electron_extracted"],
                                                interactions_chunk["z_obs"],
                                                positions,
                                                interactions_chunk["drift_time_mean"] ,
                                                interactions_chunk["sum_s2_photons"],
                                                )
        
        _photon_timings = self.photon_timings(positions,
                                              interactions_chunk["sum_s2_photons"],
                                              _photon_channels,
                                              )

        _photon_timings += np.repeat(electron_chunks[-1]["time"], electron_chunks[-1]["n_s2_photons"])

        _photon_timings = pmt_transit_time_spread(_photon_timings=_photon_timings,
                                                  pmt_transit_time_mean=self.pmt_transit_time_mean,
                                                  pmt_transit_time_spread=self.pmt_transit_time_spread,
                                                  rng=self.rng,
                                                  )

        _photon_gains, _photon_is_dpe = photon_gain_calculation(_photon_channels=_photon_channels,
                                                                p_double_pe_emision=self.p_double_pe_emision,
                                                                gains=self.gains,
                                                                spe_scaling_factor_distributions=self.spe_scaling_factor_distributions,
                                                                rng=self.rng,
                                                                )

        result = build_photon_propagation_output(dtype=self.dtype,
                                                 _photon_timings=_photon_timings,
                                                 _photon_channels=_photon_channels,
                                                 _photon_gains=_photon_gains,
                                                 _photon_is_dpe=_photon_is_dpe,
                                                 )
        
        result = strax.sort_by_time(result)

        chunk = self.chunk(start=last_start, end=end, data=result)
        yield chunk

       
    def photon_channels(self, n_electron, z_obs, positions, drift_time_mean, n_photons):
        
        channels = np.arange(self.n_tpc_pmts).astype(np.int64)
        top_index = np.arange(self.n_top_pmts)
        channels_bottom = np.arange(self.n_top_pmts, self.n_tpc_pmts)
        bottom_index = np.array(channels_bottom)
        
        if self.diffusion_constant_transverse > 0:
            pattern = self.s2_pattern_map_diffuse(n_electron, z_obs, positions, drift_time_mean)  # [position, pmt]
        else:
            pattern = self.s2_pattern_map(positions)  # [position, pmt]
            
        if pattern.shape[1] - 1 not in bottom_index:
            pattern = np.pad(pattern, [[0, 0], [0, len(bottom_index)]], 
                             'constant', constant_values=1)
        
        # Remove turned off pmts
        pattern[:, np.in1d(channels, self.turned_off_pmts)] = 0
        
        sum_pat = np.sum(pattern, axis=1).reshape(-1, 1)
        pattern = np.divide(pattern, sum_pat, out=np.zeros_like(pattern), where=sum_pat != 0)

        assert pattern.shape[0] == len(positions)
        assert pattern.shape[1] == len(channels)
        
        _buffer_photon_channels = []
        # Randomly assign to channel given probability of each channel
        for i, n_ph in enumerate(n_photons):
            pat = pattern[i]
            
            #Redistribute pattern with user specified aft smearing
            if self.s2_aft_sigma != 0: 
                _cur_aft=np.sum(pat[top_index])/np.sum(pat)
                _new_aft=_cur_aft*skewnorm.rvs(loc=1.0, scale=self.s2_aft_sigma, a=self.s2_aft_skewness)
                _new_aft=np.clip(_new_aft, 0, 1)
                pat[top_index]*=(_new_aft/_cur_aft)
                pat[bottom_index]*=(1 - _new_aft)/(1 - _cur_aft)
            
            # Pattern map return zeros   
            if np.isnan(pat).sum() > 0:  
                _photon_channels = np.array([-1] * n_ph)
                
            else:
                _photon_channels = self.rng.choice(channels,
                                                    size=n_ph,
                                                    p=pat,
                                                    replace=True)
                
            _buffer_photon_channels.append(_photon_channels)
        
        _photon_channels = np.concatenate(_buffer_photon_channels)
        
        return _photon_channels.astype(np.int64)

    
    def s2_pattern_map_diffuse(self, n_electron, z, xy, drift_time_mean):
        """Returns an array of pattern of shape [n interaction, n PMTs]
        pattern of each interaction is an average of n_electron patterns evaluated at
        diffused position near xy. The diffused positions sample from 2d symmetric gaussian
            with spread scale with sqrt of drift time.
        :param n_electron: a 1d int array
        :param z: a 1d float array
        :param xy: a 2d float array of shape [n interaction, 2]
        :param config: dict of the wfsim config
        :param resource: instance of the resource class
        """
        assert all(z < 0), 'All S2 in liquid should have z < 0'

        if self.enable_field_dependencies['diffusion_transverse_map']:
            diffusion_constant_radial = self.field_dependencies_map(z, xy, map_name='diffusion_radial_map')  # cm²/s
            diffusion_constant_azimuthal = self.field_dependencies_map(z, xy, map_name='diffusion_azimuthal_map') # cm²/s
            diffusion_constant_radial *= 1e-9  # cm²/ns
            diffusion_constant_azimuthal *= 1e-9  # cm²/ns
        else:
            #diffusion_constant_transverse = diffusion_constant_transverse
            diffusion_constant_radial = self.diffusion_constant_transverse
            diffusion_constant_azimuthal = self.diffusion_constant_transverse

        hdiff = np.zeros((np.sum(n_electron), 2))
        hdiff = simulate_horizontal_shift(n_electron, drift_time_mean,xy, diffusion_constant_radial, diffusion_constant_azimuthal, hdiff, self.rng)

        # Should we also output this xy position in truth?
        xy_multi = np.repeat(xy, n_electron, axis=0) + hdiff  # One entry xy per electron
        # Remove points outside tpc, and the pattern will be the average inside tpc
        # Should be done naturally with the s2 pattern map, however, there's some bug there, so we apply this hard cut
        mask = np.sum(xy_multi ** 2, axis=1) <= self.tpc_radius ** 2

        output_dim = self.s2_pattern_map.data['map'].shape[-1]

        pattern = np.zeros((len(n_electron), output_dim))
        n0 = 0
        # Average over electrons for each s2
        for ix, ne in enumerate(n_electron):
            s = slice(n0, n0+ne)
            pattern[ix, :] = np.average(self.s2_pattern_map(xy_multi[s][mask[s]]), axis=0)
            n0 += ne

        return pattern

    def singlet_triplet_delays(self, size, singlet_ratio):
        """
        Given the amount of the excimer, return time between excimer decay
        and their time of generation.
        size           - amount of excimer
        self.phase     - 'liquid' or 'gas'
        singlet_ratio  - fraction of excimers that become singlets
                         (NOT the ratio of singlets/triplets!)
        """
        if self.phase_s2 == 'liquid':
            t1, t3 = (self.singlet_lifetime_liquid,
                      self.triplet_lifetime_liquid)
        elif self.phase_s2 == 'gas':
            t1, t3 = (self.singlet_lifetime_gas,
                      self.triplet_lifetime_gas)
        else:
            t1, t3 = 0, 0

        delay = self.rng.choice([t1, t3], size, replace=True,
                                 p=[singlet_ratio, 1 - singlet_ratio])
        return (self.rng.exponential(1, size) * delay).astype(np.int64)
    
    def photon_timings(self, positions, n_photons, _photon_channels):
        raise NotImplementedError # This is implemented in the child class

    
@export
class S2PhotonPropagation(S2PhotonPropagationBase):
    """
    This class is used to simulate the propagation of photons from an S2 signal using 
    luminescence timing from garfield gasgap, singlet and tripled delays and optical propagation
    """
    __version__ = "0.1.0"
    
    child_plugin = True

    s2_luminescence_map = straxen.URLConfig(
        default = 'simple_load://resource://simulation_config://'
                  'SIMULATION_CONFIG_FILE.json?'
                  '&key=s2_luminescence_gg'
                  '&fmt=npy',
        cache=True,
        help='Luminescence map for S2 Signals',
    )

    garfield_gas_gap_map = straxen.URLConfig(
        default = 'itp_map://resource://simulation_config://'
                  'SIMULATION_CONFIG_FILE.json?'
                  '&key=garfield_gas_gap_map'
                  '&fmt=json',
        cache=True,
        help='Garfield gas gap map',
    )

    s2_optical_propagation_spline = straxen.URLConfig(
        default = 'itp_map://resource://simulation_config://'
                  'SIMULATION_CONFIG_FILE.json?'
                  '&key=s2_time_spline'
                  '&fmt=json.gz',
        cache=True,
        help='Spline for the optical propagation of S2 signals',
    )

    def setup(self):
        super().setup()
        log.debug(f"Using Garfield GasGap luminescence timing and optical propagation with plugin version {self.__version__}")

    def photon_timings(self, positions, n_photons, _photon_channels):

        _photon_timings = self.luminescence_timings_garfield_gasgap(positions, n_photons)

        # Emission Delay
        _photon_timings += self.singlet_triplet_delays(len(_photon_timings), self.singlet_fraction_gas)
        
        # Optical Propagation Delay
        _photon_timings += self.optical_propagation(_photon_channels)
        
        return _photon_timings

    def luminescence_timings_garfield_gasgap(self, xy, n_photons):
        """
        Luminescence time distribution computation according to garfield scintillation maps
        which are ONLY drawn from below the anode, and at different gas gaps
        :param xy: 1d array with positions
        :param n_photons: 1d array with ints for number of xy positions
        returns 2d array with ints for photon timings of input param 'shape'
        """
        #assert 's2_luminescence_gg' in resource.__dict__, 's2_luminescence_gg model not found'
        assert len(n_photons) == len(xy), 'Input number of n_electron should have same length as positions'

        d_gasgap = self.s2_luminescence_map['gas_gap'][1]-self.s2_luminescence_map['gas_gap'][0]

        cont_gas_gaps = self.garfield_gas_gap_map(xy)
        draw_index = np.digitize(cont_gas_gaps, self.s2_luminescence_map['gas_gap'])-1
        diff_nearest_gg = cont_gas_gaps - self.s2_luminescence_map['gas_gap'][draw_index]

        return draw_excitation_times(self.s2_luminescence_map['timing_inv_cdf'],
                                     draw_index,
                                     n_photons,
                                     diff_nearest_gg,
                                     d_gasgap,
                                     self.rng
                                    )

    def optical_propagation(self, channels):
        """Function getting times from s2 timing splines:
        :param channels: The channels of all s2 photon
        """
        prop_time = np.zeros_like(channels)
        u_rand = self.rng.random(len(channels))[:, None]

        is_top = channels < self.n_top_pmts
        prop_time[is_top] = self.s2_optical_propagation_spline(u_rand[is_top], map_name='top')

        is_bottom = channels >= self.n_top_pmts
        prop_time[is_bottom] = self.s2_optical_propagation_spline(u_rand[is_bottom], map_name='bottom')

        return prop_time.astype(np.int64)

@export
class S2PhotonPropagationSimple(S2PhotonPropagationBase):
    """
    This class is used to simulate the propagation of photons from an S2 signal using 
    the simple liminescence model, singlet and tripled delays and optical propagation
    """
    __version__ = "0.1.0"
    
    child_plugin = True

    pressure = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=pressure",
        type=(int, float),
        cache=True,
        help='pressure',
    )

    temperature = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=temperature",
        type=(int, float),
        cache=True,
        help='temperature',
    )

    gas_drift_velocity_slope = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=gas_drift_velocity_slope",
        type=(int, float),
        cache=True,
        help='gas_drift_velocity_slope',
    )

    enable_gas_gap_warping = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=enable_gas_gap_warping",
        type=(int, float),
        cache=True,
        help='enable_gas_gap_warping',
    )

    elr_gas_gap_length = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=elr_gas_gap_length",
        type=(int, float),
        cache=True,
        help='elr_gas_gap_length',
    )

    gas_gap_map = straxen.URLConfig(
        default = 'simple_load://resource://simulation_config://'
                  'SIMULATION_CONFIG_FILE.json?'
                  '&key=gas_gap_map'
                  '&fmt=pkl',
        cache=True,
        help='gas_gap_map',
    )

    anode_field_domination_distance = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=anode_field_domination_distance",
        type=(int, float),
        cache=True,
        help='anode_field_domination_distance',
    )

    anode_wire_radius = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=anode_wire_radius",
        type=(int, float),
        cache=True,
        help='anode_wire_radius',
    )

    gate_to_anode_distance = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=gate_to_anode_distance",
        type=(int, float),
        cache=True,
        help='gate_to_anode_distance',
    )

    anode_voltage = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=anode_voltage",
        type=(int, float),
        cache=True,
        help='anode_voltage',
    )

    lxe_dielectric_constant = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=lxe_dielectric_constant",
        type=(int, float),
        cache=True,
        help='lxe_dielectric_constant',
    )

    s2_optical_propagation_spline = straxen.URLConfig(
        default = 'itp_map://resource://simulation_config://'
                  'SIMULATION_CONFIG_FILE.json?'
                  '&key=s2_time_spline'
                  '&fmt=json.gz',
        cache=True,
        help='s2_optical_propagation_spline',
    )

    def setup(self):
        super().setup()
        log.debug("Using simple luminescence timing and optical propagation")
        log.warn("This is a legacy option, do you really want to use the simple luminescence model?")

    def photon_timings(self, positions, n_photons, _photon_channels):

        _photon_timings = self.luminescence_timings_simple(positions, n_photons)

        # Emission Delay
        _photon_timings += self.singlet_triplet_delays(len(_photon_timings), self.singlet_fraction_gas)
        
        # Optical Propagation Delay
        _photon_timings += self.optical_propagation(_photon_channels)
        
        return _photon_timings

    def luminescence_timings_simple(self, xy, n_photons):

        """
        Luminescence time distribution computation according to simple s2 model (many many many single electrons)
        :param xy: 1d array with positions
        :param n_photons: 1d array with ints for number of xy positions
        :param config: dict wfsim config
        :param resource: instance of wfsim resource
        returns _luminescence_timings_simple
        """
        assert len(n_photons) == len(xy), 'Input number of n_photons should have same length as positions'

        number_density_gas = self.pressure / \
            (constants.Boltzmann/constants.elementary_charge * self.temperature)
        alpha = self.gas_drift_velocity_slope / number_density_gas
        uE = 1000 / 1 #V/cm
        pressure = self.pressure / conversion_to_bar

        if self.enable_gas_gap_warping:
            dG = self.gas_gap_map.lookup(*xy.T)
            dG = np.ma.getdata(dG) #Convert from masked array to ndarray?
        else:
            dG = np.ones(len(xy)) * self.elr_gas_gap_length
        rA = self.anode_field_domination_distance
        rW = self.anode_wire_radius
        dL = self.gate_to_anode_distance - dG

        VG = self.anode_voltage / (1 + dL / dG / self.lxe_dielectric_constant)
        E0 = VG / ((dG - rA) / rA + np.log(rA / rW))  # V / cm

        dr = 0.0001  # cm
        r = np.arange(np.max(dG), rW, -dr)
        rr = np.clip(1 / r, 1 / rA, 1 / rW)

        return _luminescence_timings_simple(len(xy), dG, E0, 
                                            r, dr, rr, alpha, uE,
                                            pressure, n_photons)

    def optical_propagation(self, channels):
        """Function getting times from s2 timing splines:
        :param channels: The channels of all s2 photon
        """
        prop_time = np.zeros_like(channels)
        u_rand = self.rng.random(len(channels))[:, None]

        is_top = channels < self.n_top_pmts
        prop_time[is_top] = self.s2_optical_propagation_spline(u_rand[is_top], map_name='top')

        is_bottom = channels >= self.n_top_pmts
        prop_time[is_bottom] = self.s2_optical_propagation_spline(u_rand[is_bottom], map_name='bottom')

        return prop_time.astype(np.int64)

@njit
def draw_excitation_times(inv_cdf_list, hist_indices, nph, diff_nearest_gg, d_gas_gap, rng):
    
    """
    Draws the excitation times from the GARFIELD electroluminescence map
    
    :param inv_cdf_list:       List of inverse CDFs for the excitation time histograms
    :param hist_indices:       The index of the histogram which refers to the gas gap
    :param nph:                A 1-d array of the number of photons per electron
    :param diff_nearest_gg:    The difference between the gas gap from the map
                               (continuous value) and the nearest (discrete) value
                               of the gas gap corresponding to the excitation time
                               histograms
    :param d_gas_gap:          Spacing between two consecutive gas gap values
    
    returns time of each photon
    """
    
    inv_cdf_len = len(inv_cdf_list[0])
    timings = np.zeros(np.sum(nph))
    upper_hist_ind = np.clip(hist_indices+1, 0, len(inv_cdf_list)-1)
    
    count = 0
    for i, (hist_ind, u_hist_ind, n, dngg) in enumerate(zip(hist_indices,
                                                            upper_hist_ind, 
                                                            nph,
                                                            diff_nearest_gg)):
        
        #There are only 10 values of gas gap separated by 0.1mm, so we interpolate
        #between two histograms
        
        interp_cdf = ((inv_cdf_list[u_hist_ind]-inv_cdf_list[hist_ind])*(dngg/d_gas_gap)
                       +inv_cdf_list[hist_ind])
        
        #Subtract 2 because this way we don't want to sample from this last strange tail
        samples = rng.uniform(0, inv_cdf_len-2, n)
        #samples = np.random.uniform(0, inv_cdf_len-2, n)
        t1 = interp_cdf[np.floor(samples).astype('int')]
        t2 = interp_cdf[np.ceil(samples).astype('int')]
        T = (t2-t1)*(samples - np.floor(samples))+t1
        if n!=0:
            T = T-np.mean(T)
        
        #subtract mean to get proper drift time and z correlation
        timings[count:count+n] = T
        count+=n
    return timings

@njit
def _luminescence_timings_simple(
    n,
    dG,
    E0,
    r,
    dr,
    rr,
    alpha,
    uE,
    p,
    n_photons,
    rng,
    ):
    """
    Luminescence time distribution computation, calculates emission timings of photons from the excited electrons
    return 1d nested array with ints
    """
    emission_time = np.zeros(np.sum(n_photons), np.int64)

    ci = 0
    for i in range(n):
        npho = n_photons[i]
        dt = dr / (alpha * E0[i] * rr)
        dy = E0[i] * rr / uE - 0.8 * p  # arXiv:physics/0702142
        avgt = np.sum(np.cumsum(dt) * dy) / np.sum(dy)

        j = np.argmax(r <= dG[i])
        t = np.cumsum(dt[j:]) - avgt
        y = np.cumsum(dy[j:])

        probabilities = rng.random(npho)
        emission_time[ci:ci+npho] = np.interp(probabilities, y / y[-1], t).astype(np.int64)
        ci += npho

    return emission_time

@njit()
def simulate_horizontal_shift(n_electron, drift_time_mean,xy, diffusion_constant_radial, diffusion_constant_azimuthal,result, rng):

     hdiff_stdev_radial = np.sqrt(2 * diffusion_constant_radial * drift_time_mean)
     hdiff_stdev_azimuthal = np.sqrt(2 * diffusion_constant_azimuthal * drift_time_mean)
     hdiff_radial = rng.normal(0, 1, np.sum(n_electron)) * np.repeat(hdiff_stdev_radial, n_electron)
     hdiff_azimuthal = rng.normal(0, 1, np.sum(n_electron)) * np.repeat(hdiff_stdev_azimuthal, n_electron)
     hdiff = np.column_stack((hdiff_radial, hdiff_azimuthal))
     theta = np.arctan2(xy[:,1], xy[:,0])

     sin_theta = np.sin(theta)
     cos_theta = np.cos(theta)
     matrix = build_rotation_matrix(sin_theta, cos_theta)

     split_hdiff = np.split(hdiff, np.cumsum(n_electron))[:-1]

     start_idx = np.append([0], np.cumsum(n_electron)[:-1])
     stop_idx = np.cumsum(n_electron)

     for i in range(len(matrix)):
          result[start_idx[i]: stop_idx[i]] = (matrix[i] @ split_hdiff[i].T).T 

     return result

@njit()
def build_rotation_matrix(sin_theta, cos_theta):
    matrix = np.zeros((2, 2, len(sin_theta)))
    matrix[0, 0] = cos_theta
    matrix[0, 1] = sin_theta
    matrix[1, 0] = -sin_theta
    matrix[1, 1] = cos_theta
    return matrix.T

@njit()
def find_electron_split_index(electrons, gaps, file_size_limit, min_gap_length, mean_n_photons_per_electron):
    
    n_bytes_per_photon = 23 # 8 + 8 + 4 + 2 + 1

    data_size_mb = 0
    split_index = []

    for i, (e, g) in enumerate(zip(electrons, gaps)):
        #Assumes data is later saved as int16
        data_size_mb += n_bytes_per_photon * mean_n_photons_per_electron / 1e6 

        if data_size_mb < file_size_limit: 
            continue

        if g >= min_gap_length:
            data_size_mb = 0
            split_index.append(i)

    return np.array(split_index)+1

def build_electron_index(individual_electrons, interactions_in_roi):
    "Function to match the electrons to the correct interaction_in_roi"

    electrons_split = np.split(individual_electrons, np.cumsum(interactions_in_roi["n_electron_extracted"]))[:-1]

    index = []
    k = 0
    for element in electrons_split:
        index.append(np.repeat(k, len(element)))
        k+=1
    index = np.concatenate(index)

    return index