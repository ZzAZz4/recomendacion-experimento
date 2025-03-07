import pandas as pd
import numpy as np

from annoy import AnnoyIndex

import tensorflow as tf
from tensorflow import keras
from keras.models import load_model
import random

movie_dt = pd.read_csv('movies.csv')
# Final Recommendation system
# This is the Ensemble method that combines NCF DL model with MF-ANN model.
# The ensemble recommender loads and takes recommendations from two pre-trained model,
#    and make recommendation based on user's profile by feeding the user into different model,
#    or add weights to each recommendation to make the final recommendation

class EnsembleRecommender():
    def __init__(self,rating_df,movie_df, rating_matrix, item_vector):
        # class initializer input: - rating_df  a user rating dataframe, containing 'userIds', 'movieIds', 'rating'
        #                          - movie_df   a movie info dataframe, containing 'movieIds', 'title', 'genre'
        #                          - userId     a single userId that the model is recommending for
        #                          - rating_martrix    a user-movie matrix
        #                          - item_vector       the vector representation of each movie learned by MF
        #
        # initialize the variables for recommendation functions
        self.rating_df = rating_df
        self.movie_df = movie_df
        self.user_ids = rating_df['userId'].unique()
        self.movie_ids = rating_df['movieId'].unique()
        self.user2user_encoded = {x: i for i, x in enumerate(self.user_ids)}
        self.movie2movie_encoded = {x: i for i, x in enumerate(self.movie_ids)}
        self.movie_encoded2movie = {i: x for i, x in enumerate(self.movie_ids)}
        self.rating_matrix = rating_matrix
        self.item_vector = item_vector
        

    def NCF_recommendation(self,userId,top_k=20):
        # make recommendation based on NCF model
        # input: - top_k  the number of recommendations made
        #        - userId     a single userId that the model is recommending for
        # output: a dataframe containing index as 'movieId','prediction','title','genre'
        
        # load the pre-trained NCF model
        model =  tf.keras.models.load_model('rec_model.h5')
        
        # get the encoded userId
        client_encoded = self.user2user_encoded[userId]
        
        # get user rated movies
        movie_watched = self.rating_df[self.rating_df['userId'] == userId]['movieId'].values
        
        # get the movies user have not rated in which the NCF  will recommend 
        movie_poll_encoded = []
        for item in self.movie_ids:
            if not np.isin(item, movie_watched):
                movie_poll_encoded.append(self.movie2movie_encoded[item])
        
        # encode the unrated movies into a dataframe
        movie_poll_encoded = random.sample(movie_poll_encoded, 5000)
        print("len:" , len(movie_poll_encoded))


        d = {'user_encoded': [client_encoded] * len(movie_poll_encoded), 'movie_encoded' : movie_poll_encoded}
        client_df = pd.DataFrame(d)
        
        # use the model to predict user's rating on these movies
        #print(client_df['user_encoded'], client_df['movie_encoded'])
        ratings = model.predict([client_df['user_encoded'], client_df['movie_encoded']])
        
        # sort the movies according to the predicted ratings and take top k
        top_ratings_idx = ratings.flatten().argsort()[-top_k:][::-1]
        top_ratings = ratings[top_ratings_idx].flatten()
        recommend_movieId = [self.movie_encoded2movie.get(movie_poll_encoded[x]) for x in top_ratings_idx]
        
        # format the output for better user experience
        top_movie_rec = pd.DataFrame({'movieId': recommend_movieId, 'prediction': top_ratings}).set_index('movieId')
        top_movie_rec = top_movie_rec.join(self.movie_df.set_index('movieId'))
        
        return top_movie_rec
    
    # make recommendation based on MF-ANN model
    def get_rated_movies(self,userId,threshold=3):    
        # input:  userid, a rating threshold, movies that are rated below threshold
        # will not be counted 
        # output: a list of high-scored movies that are rated by givern user, a list of corresponding ratings
        #
        all_rates = self.rating_df[self.rating_df['userId'] == userId]
        high_rates = all_rates[all_rates['rating'] >= threshold]['rating'].values
        high_rate_movie = all_rates[all_rates['rating'] >= threshold]['movieId'].values
        return high_rate_movie, high_rates

    
    def ann(self, metric, num_trees):
        # Implement Approximate Nearest Neighborhood to find similar items, save it in 'rating.ann' 
        # input: target movie, rating matrix, item_vectors, metric (can be "angular", "euclidean", "manhattan", "hamming")
        #        number of trees(More trees gives higher precision when querying)
        # output: save it in 'rating.ann' 
        #
        # construct a dictionary where movied id contains its vector representation 
        print("movies_ids",len(self.movie_ids))
        rating_dictionary = {self.movie_ids[i]: self.item_vector[i] for i in range(19835)} 
        # ann method
        f = len(self.item_vector[1])
        t = AnnoyIndex(f, metric)  # Length of item vector that will be indexed
        for key in rating_dictionary:
            t.add_item(key, rating_dictionary.get(key))
        t.build(num_trees) # 10 trees
        t.save('rating.ann')

    
    def ANN_recommendation(self,userId, dimension = 14, metric = 'angular',
                           num_tree=10, threshold=4, top_n=10):
        # use the trained ANN model to recommend the nearest movies to user's rated movies
        # input: - dimension,metric,
        #          num_tree,threshold,   learned parameter from ANN cv
        #          top_n   
        # output: a dataframe containing index as 'movieId','title','genre'
        #
        v = self.item_vector
        self.ann(metric, num_tree) 
        f = len(v[1])
        u = AnnoyIndex(f, metric)
        u.load('rating.ann')
        
        # construct the recommendation for the user
        high_rate_movie, rate = self.get_rated_movies(userId,threshold=threshold)
        movielist = []
        distancelist = []
        
        if len(high_rate_movie) >= 1:
            # find neighborhood of each movies in the high rated movie set
            for movieid in high_rate_movie:
                movie, dist = u.get_nns_by_item(movieid, top_n, include_distances=True)
                movielist.extend(movie[1:])
                
                # get the weighted distance based on rating scores
                weighted_dist = (np.array(dist[1:])/rate[np.where(high_rate_movie == movieid)]).tolist()
                distancelist.extend(weighted_dist)  
                
            #if more than 20 movies are chosen to recommend to user, choose 20 nearest item for this user
            if len(movielist) > 20:
                sorted_recommend = np.array(movielist)[np.array(distancelist).argsort()]
                movielist = sorted_recommend[:20]
        
        # construct a dataframe for final output
        top_movie_rec = self.movie_df.loc[self.movie_df['movieId'].isin(movielist)].set_index('movieId')
        
        return top_movie_rec
    
    
    def Popular_recommendation(self, top_k = 20):
        # recommend only the most popular movies to the user
        # define popularity as: at least 1000 reviews, 
        #                       at least 4.0 average rating
        # output: a dataframe containing the top_k most popular movies
        #
        # calculate the average rating and number of reviews for each movie
        grouped_rating = self.rating_df.groupby('movieId')['rating'].mean()
        grouped_count = self.rating_df.groupby('movieId')['movieId'].count()
        
        # form them into datasets
        df_grouped = pd.DataFrame(grouped_count)
        df_grouped.columns = ['count']

        df_group_avg = pd.DataFrame(grouped_rating)
        df_group_avg.columns = ['avg_rating']
        
        # join two datasets and order by count and avg_rating
        df_grouped = df_grouped.join(df_group_avg, on ='movieId')
        df_grouped.sort_values(by=['count','avg_rating'], ascending=False)
        
        # get the top_k movies
        top_k_rec = df_grouped.loc[df_grouped['count'] > 1000].loc[df_grouped['avg_rating']>4.0][:top_k]
        
        # construct a dataframe for final output
        top_movie_rec = self.movie_df.loc[self.movie_df['movieId'].isin(top_k_rec.index.values)].set_index('movieId')
        
        return top_movie_rec
    
    def User_Classification(self,userId):
        # classify users based on the number of movies they have rated to decide how to recommend
        # input: - userId     a single userId that the model is recommending for
        # output: the classification of user's rating record with value '0','1-50','51-150','151'
        #
        if userId not in self.user_ids:
            return '0'
        else:
            num_of_rated_movies = len(self.rating_df.loc[self.rating_df.userId == userId]['movieId'].unique())
            print("numeber of rated: ", num_of_rated_movies)

            return '51-150'
          
    
    
    def Recommend(self, userId):
        # if the user have not rated any movies, recommend the most popular movies
        # if the user have rated 1 - 50 movies, recommend with NCF model only
        # if the user have rated 51 - 150 movies, recommend with both NCF and ANN model, with more weights on NCF model
        # if the user have rated more than 151 movies, recommend with both NCF and ANN model, with equal weights
        # input: - userId     a single userId that the model is recommending for
        # output: the comprehensive recommendation for the specific user
        # 
        return self.NCF_recommendation(userId)[:1]
        #return self.NCF_recommendation(userId)[:2].append(self.ANN_recommendation(userId).sample(3))
        
