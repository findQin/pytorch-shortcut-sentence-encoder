import torch
from torch import nn


class LSTMLayer:
    def __init__(self, hidden_size, num_layers, bidirectional):
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.bidirectional = bidirectional
        self.output_size = self.hidden_size
        if bidirectional:
            self.output_size *= 2


class ResidualStackedEncoder(nn.Module):
    def __init__(self,
                 max_sentence_length,
                 embedding_vectors,
                 padding_index,
                 layers_def,
                 device):
        super(ResidualStackedEncoder, self).__init__()
        self.padding_index = padding_index
        self.embedding_dim = len(embedding_vectors[0])
        self.device = device
        self.embedding = nn.Embedding.from_pretrained(embedding_vectors, freeze=False, padding_idx=padding_index)
        self.max_sentence_length = max_sentence_length

        layers = []
        input_size = self.embedding_dim
        layer = layers_def[0]
        lstm = nn.LSTM(input_size,
                       hidden_size=layer.hidden_size,
                       batch_first=True,
                       bidirectional=layer.bidirectional,
                       num_layers=layer.num_layers)
        layers.append(lstm)

        input_size += layer.output_size
        for layer in layers_def[1:]:
            lstm = nn.LSTM(input_size,
                           hidden_size=layer.hidden_size,
                           batch_first=True,
                           bidirectional=layer.bidirectional,
                           num_layers=layer.num_layers)
            layers.append(lstm)

        self.lstm_layers = nn.Sequential(*layers)

        # Row max pooling
        self.pooling = nn.MaxPool1d(kernel_size=max_sentence_length, stride=max_sentence_length)

        # Output size
        self.last_layer_out = layers_def[-1].output_size

        self.output_size = (self.last_layer_out * max_sentence_length) // max_sentence_length

    def forward(self, x, l, sort):
        x = self.embedding(x)

        x = torch.nn.utils.rnn.pack_padded_sequence(x, l,
                                                    enforce_sorted=sort,
                                                    batch_first=True)
        x, _ = torch.nn.utils.rnn.pad_packed_sequence(x,
                                                      batch_first=True,
                                                      padding_value=self.padding_index)
        embeds = x
        lstm_output_sum = None
        for i, layer in enumerate(self.lstm_layers):
            lstm_out, _ = self.forward_lstm_layer(layer, x, l, sort)
            if i == 0:
                # First
                x = torch.cat((lstm_out, x), dim=2)
                lstm_output_sum = lstm_out
            elif i == len(self.lstm_layers) - 1:
                # Last
                x = lstm_out
            else:
                # Middle
                # Sum lstm outputs
                lstm_output_sum += lstm_out
                # Concat sum with the original embeddings
                x = torch.cat((lstm_output_sum, embeds), dim=2)

        # Pad
        pad = torch.zeros(len(x), self.max_sentence_length, self.last_layer_out).to(self.device)
        pad[:, :x.shape[1], :] = x
        x = pad

        # Pool
        x = self.pooling(x.permute(0, 2, 1)).permute(0, 2, 1)

        # Flatten
        x = x.contiguous().view(len(x), -1)

        # x = self.pooling(x.permute(0, 2, 1)).permute(0, 2, 1)
        #
        # x = x.contiguous().view(len(x), -1)
        #
        # pad = torch.zeros(len(x), self.output_size).to(self.device)
        # pad[:, :x.shape[1]] = x

        return x

    def forward_lstm_layer(self, layer, x, l, sort):
        lstm_in = torch.nn.utils.rnn.pack_padded_sequence(x, l,
                                                          enforce_sorted=sort,
                                                          batch_first=True)

        lstm_out, (hn, cn) = layer(lstm_in)

        lstm_out_unpack, _ = torch.nn.utils.rnn.pad_packed_sequence(lstm_out,
                                                                    batch_first=True,
                                                                    padding_value=self.padding_index)

        return lstm_out_unpack, (hn, cn)
